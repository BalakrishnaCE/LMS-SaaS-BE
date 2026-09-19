const { chromium } = require('playwright-core');
const fs = require('fs');

async function generatePDF() {
    const args = process.argv.slice(2);
    let inputHtmlPath = '';
    let outputPdfPath = '';

    for (let i = 0; i < args.length; i++) {
        if (args[i] === '--input') inputHtmlPath = args[i + 1];
        if (args[i] === '--output') outputPdfPath = args[i + 1];
    }

    if (!inputHtmlPath || !outputPdfPath) {
        console.error('Usage: node generate.js --input <path_to_html> --output <path_to_pdf>');
        process.exit(1);
    }

    if (!fs.existsSync(inputHtmlPath)) {
        console.error(`Input file not found: ${inputHtmlPath}`);
        process.exit(1);
    }

    try {
        const htmlContent = fs.readFileSync(inputHtmlPath, 'utf8');

        // Launch playwright
        const browser = await chromium.launch({
            executablePath: '/usr/bin/google-chrome-stable',
            args: ['--no-sandbox', '--disable-setuid-sandbox']
        });
        
        // SECURITY FIX: Disable JavaScript execution to prevent Server-Side XSS / SSRF 
        // if a malicious admin injects <script> tags into the Certificate Template
        const context = await browser.newContext({
            javaScriptEnabled: false,
            viewport: { width: 1056, height: 816 }
        });
        const page = await context.newPage();
        
        // SECURITY FIX: Prevent CSS-based SSRF via network interception
        await page.route('**/*', (route) => {
            const url = new URL(route.request().url());
            
            // Allow data: URIs (for inline base64 images/signatures)
            if (url.protocol === 'data:') {
                return route.continue();
            }
            
            // Block private / local / metadata IP ranges (RFC1918, link-local, loopback)
            const hostname = url.hostname;
            if (
                hostname === 'localhost' ||
                hostname === '127.0.0.1' ||
                hostname === '0.0.0.0' ||
                hostname.startsWith('10.') ||
                hostname.startsWith('192.168.') ||
                hostname.startsWith('169.254.') ||
                /^172\.(1[6-9]|2[0-9]|3[0-1])\./.test(hostname)
            ) {
                console.warn(`SSRF Blocked: Attempted to fetch internal/metadata IP: ${url.href}`);
                return route.abort();
            }
            
            // Allow external fetches (e.g. Google Fonts)
            return route.continue();
        });
        
        // Wrap the raw HTML in a proper document with zero margin to prevent 8px body margin from pushing content down
        const fullHtml = `
            <!DOCTYPE html>
            <html>
            <head>
                <style>
                    body, html { margin: 0; padding: 0; box-sizing: border-box; width: 1056px; height: 816px; overflow: hidden; }
                </style>
            </head>
            <body>
                ${htmlContent}
            </body>
            </html>
        `;
        
        // We set the content directly
        await page.setContent(fullHtml, { waitUntil: 'networkidle' });

        // Generate PDF matching exact template size
        await page.pdf({
            path: outputPdfPath,
            width: '1056px',
            height: '816px',
            printBackground: true,
            margin: { top: 0, right: 0, bottom: 0, left: 0 }
        });

        await browser.close();
        console.log('PDF generated successfully.');
        process.exit(0);

    } catch (error) {
        console.error('Error generating PDF:', error);
        process.exit(1);
    }
}

generatePDF();
