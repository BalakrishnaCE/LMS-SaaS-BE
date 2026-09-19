# LMS SaaS PDF Engine

This directory contains the backend PDF generation microservice for the LMS SaaS application. It is executed by Frappe's Python background workers via a `subprocess.run` bridge.

## Why is this a separate Node.js folder?

You might wonder why we don't just put PDF generation inside the `lms-portal` React frontend. Doing so would violate several core architectural rules of the LMS SaaS:
1. **Playwright OS Requirements:** `playwright-core` requires OS-level bindings to spawn and control a headless Chrome process. This cannot run in a user's web browser.
2. **Scalability:** Generating PDFs heavily consumes CPU and RAM. Forcing the admin's frontend browser to generate 500 certificates would freeze their browser and crash the app. Moving this to the backend allows Frappe to queue thousands of generation tasks asynchronously in the background.
3. **Frontend Performance:** Bundling frontend PDF generators (like `html2pdf.js`) adds massive bloat to the React bundle, slowing down login and initial load times for all learners.
4. **Security:** Generating certificates on the frontend requires trusting the client's data. By doing it on the backend, the Frappe worker fetches the true score from the database, preventing learners from tampering with their certificates.

## Technical Rationale: Why Playwright-Core?

During the architecture phase, several alternatives were evaluated and rejected for specific technical reasons (documented in `ADR-028` and `ADR-028a`).

### 1. Why not native Python libraries (WeasyPrint, wkhtmltopdf)?
Frappe is a Python framework, so using a Python library is the default Frappe approach. However, tools like WeasyPrint or `wkhtmltopdf` (which uses a decade-old QtWebKit engine) have extremely poor support for modern CSS (Flexbox, CSS Grid, complex gradients, absolute positioning). 
Because our LMS allows administrators to design certificates using modern web standards (via Tailwind CSS), we **must** use a real, modern Chromium rendering engine to ensure the generated PDF is pixel-perfect and exactly matches the frontend UI preview.

### 2. Why Playwright-Core over Puppeteer?
Initially, we used `puppeteer`. However, `puppeteer` automatically downloads its own isolated Chromium binary into the `node_modules` cache (which is ~377MB per environment). On a multi-tenant SaaS server with many apps, this causes massive disk bloat, slows down deployments, and often breaks due to missing shared Linux libraries (`libX11`, `libnss3`, etc.).
We migrated to `playwright-core`. The `-core` package contains **only** the API bindings (it is tiny, ~4MB) and relies entirely on the system's native `/usr/bin/google-chrome-stable` installation. This provides a zero-bloat Node environment and relies on Ubuntu's native package manager to keep Chrome updated and secure.

### 3. Why not a SaaS API (e.g., pdf-api.com)?
Generating PDFs via a third-party API introduces latency, costs money per generation, and raises data privacy concerns (sending learner PII to a third-party server). Doing it locally on the Frappe server is free, instant, and keeps all tenant data strictly within our infrastructure.

## Architecture

1. Frappe (`lms.backend.api.common.certificate.generate_pdf_worker`) receives a request.
2. Frappe pulls the learner's data, injects it into the HTML template, and writes the raw HTML to a temporary file.
3. Frappe calls `node generate.js` (wrapped in bash to source NVM).
4. `generate.js` launches a headless instance of `/usr/bin/google-chrome-stable` using `playwright-core`.
5. Playwright intercepts network requests to block SSRF attacks, renders the HTML, and snapshots it to a PDF file.
6. Frappe reads the PDF file, attaches it to the database, and cleans up temp files.

## Server Prerequisites (New Deployments)

When deploying this app to a new Ubuntu 24.04 server, you must install the following prerequisites. **Do not use `apt install chromium-browser`** (it installs a Snap wrapper that breaks background pathing).

### 1. Install Google Chrome Stable natively
```bash
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install -y ./google-chrome-stable_current_amd64.deb
rm google-chrome-stable_current_amd64.deb
```
Verify it exists at `/usr/bin/google-chrome-stable`.

### 2. Install Node.js 20+
Playwright requires Node.js v20 or higher.
If using `nvm`, install it for the `frappe` user:
```bash
nvm install 20
nvm alias default 20
```

### 3. Install Dependencies
```bash
cd /home/frappe/frappe-bench/apps/lms/pdf_engine
npm install
```

## Security: CSS SSRF Blocking

Because administrators can write custom HTML/CSS for Certificate Templates, there is a risk of Server-Side Request Forgery (SSRF) if they include CSS like `background: url(http://169.254.169.254/latest/meta-data/)`. 

To mitigate this, `generate.js` actively intercepts all network requests during the browser layout phase. It automatically **aborts** any requests pointing to:
- `127.0.0.1` / `localhost` / `0.0.0.0`
- `10.*.*.*`
- `192.168.*.*`
- `172.16.0.0/12`
- `169.254.*.*` (AWS Metadata)

It safely allows public requests (like Google Fonts) and inline `data:` URIs (like Base64 signature images).

