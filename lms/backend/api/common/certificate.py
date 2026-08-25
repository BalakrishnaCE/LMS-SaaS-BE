import frappe
from frappe.utils import getdate

@frappe.whitelist(allow_guest=False)
def download_certificate_pdf(certificate_name):
    """Generate a PDF certificate that matches the template preview.

    wkhtmltopdf uses an old WebKit with NO flexbox/grid support, so the
    template's own CSS is stripped and replaced with an equivalent
    display:table layout.  The template's HTML markup, colours, fonts
    and decorative elements are used exactly as stored in the database.
    """
    import re, base64, os as _os

    if not certificate_name:
        frappe.throw("Certificate name is required")

    cert = frappe.get_doc("LMS Certificate", certificate_name)

    if cert.certificate_pdf:
        frappe.local.response.update({"type": "redirect", "location": cert.certificate_pdf})
        return

    # ── Fetch data ────────────────────────────────────────────────────────────
    try:
        learner_name = frappe.get_doc("User", cert.user).full_name or cert.user
    except Exception:
        learner_name = cert.user

    try:
        module_name = frappe.get_doc("LMS Module", cert.module).module_name
    except Exception:
        module_name = cert.module

    html_template = ""
    if cert.template:
        try:
            html_template = frappe.db.get_value(
                "LMS Certificate Template", cert.template, "html_template") or ""
        except Exception:
            pass

    if not html_template and cert.module:
        try:
            mod = frappe.get_doc("LMS Module", cert.module)
            if mod.certificate_template:
                html_template = frappe.db.get_value(
                    "LMS Certificate Template", mod.certificate_template, "html_template") or ""
        except Exception:
            pass

    if not html_template:
        frappe.throw("No certificate template found for this certificate")

    issue_date = ""
    if cert.issued_on:
        try:
            issue_date = getdate(cert.issued_on).strftime("%B %d, %Y")
        except Exception:
            issue_date = str(cert.issued_on)

    score_val = str(int(cert.score)) if cert.score else "N/A"
    cert_id   = cert.certificate_id or cert.name

    # ── Replace placeholders ──────────────────────────────────────────────────
    html_body = html_template
    html_body = html_body.replace("{{learner_name}}",   frappe.utils.escape_html(learner_name))
    html_body = html_body.replace("{{module_name}}",    frappe.utils.escape_html(module_name))
    html_body = html_body.replace("{{date}}",           frappe.utils.escape_html(issue_date))
    html_body = html_body.replace("{{score}}",          frappe.utils.escape_html(score_val))
    html_body = html_body.replace("{{certificate_id}}", frappe.utils.escape_html(cert_id))
    html_body = html_body.replace("{{signature_by}}", "")

    # ── Strip ALL <style> blocks from the template ────────────────────────────
    # wkhtmltopdf uses an old WebKit that has NO flexbox support.
    # The template's CSS is flex-based so it will not render correctly.
    # We keep only the HTML markup (colours come from inline styles on elements
    # or from our replacement CSS below which uses table layout).
    html_body = re.sub(r"<style[^>]*>.*?</style>", "", html_body,
                       flags=re.DOTALL | re.IGNORECASE)

    # ── Fetch template colours by peeking at the raw CSS ─────────────────────
    # (already stripped above; we use hardcoded palette that matches both templates)
    # Classic palette: FAF5F0 bg, BB6707 border, F5A74C dashed, 714109 title,
    #                  595F69 labels, 17191C name, 9CA1AB foot-label
    # We reconstruct the visual design using table layout.

    # ── Embed fonts ───────────────────────────────────────────────────────────
    def _font_b64(path):
        try:
            with open(path, "rb") as f:
                return "data:font/woff2;base64," + base64.b64encode(f.read()).decode()
        except Exception:
            return None

    _dist = _os.path.normpath(_os.path.join(
        _os.path.dirname(_os.path.abspath(__file__)),
        "..", "..", "..", "lms-portal", "dist", "assets",
    ))
    _jakarta_latin = _font_b64(_os.path.join(_dist, "plus-jakarta-sans-latin-wght-normal-eXO_dkmS.woff2"))
    _jakarta_ext   = _font_b64(_os.path.join(_dist, "plus-jakarta-sans-latin-ext-wght-normal-DmpS2jIq.woff2"))

    _fonts = ""
    if _jakarta_latin:
        _fonts += f"@font-face{{font-family:'Plus Jakarta Sans';font-style:normal;font-weight:400;src:url('{_jakarta_latin}')format('woff2');}}\n"
        _fonts += f"@font-face{{font-family:'Plus Jakarta Sans';font-style:normal;font-weight:600;src:url('{_jakarta_latin}')format('woff2');}}\n"
        _fonts += f"@font-face{{font-family:'Plus Jakarta Sans';font-style:normal;font-weight:700;src:url('{_jakarta_latin}')format('woff2');}}\n"
    _fonts += (
        "@font-face{font-family:'Instrument Serif';font-style:normal;font-weight:400;"
        "src:local('Georgia'),local('DejaVu Serif');}\n"
        "@font-face{font-family:'Instrument Serif';font-style:italic;font-weight:400;"
        "src:local('Georgia Italic'),local('DejaVu Serif');}\n"
        "@font-face{font-family:'Parisienne';font-style:normal;font-weight:400;"
        "src:local('Georgia'),local('DejaVu Serif');}\n"
    )

    # ── Replacement CSS (table layout — fully supported by wkhtmltopdf) ───────
    # A4 landscape: 297mm × 210mm = 1122pt × 793px at 96dpi
    # wkhtmltopdf's old WebKit supports: display:table, position:absolute,
    # border, padding, background, font-* but NOT flex/grid/clamp/vw/vh.
    layout_css = """
/* ===== PAGE ===== */
@page { size: 297mm 210mm; margin: 0; }
html, body { margin:0; padding:0; width:297mm; height:210mm; overflow:hidden;
             font-family:'Plus Jakarta Sans',Arial,sans-serif; background:#FAF5F0; }

/* ===== TOP-LEVEL WRAPPER — fills the whole page ===== */
.certificate-wrapper {
  display: block;
  width: 297mm;
  height: 210mm;
  background: #FAF5F0;
  border: 3px solid #BB6707;
  border-radius: 8px;
  padding: 18px;
  box-sizing: border-box;
  position: relative;
}
/* Hide the original paper div — wrapper IS the paper now */
.certificate-paper { display: contents; }

/* ===== INNER DASHED GOLD FRAME ===== */
.inner-gold-frame {
  position: absolute;
  top: 18px; left: 18px; right: 18px; bottom: 18px;
  border: 1px dashed #F5A74C;
  box-sizing: border-box;
}

/* ===== TITLE — top-center ===== */
.cert-title {
  display: block;
  width: 100%;
  text-align: center;
  font-family: 'Instrument Serif', Georgia, serif;
  font-weight: 400;
  font-size: 30pt;
  color: #714109;
  margin: 20px 0 6px;
  padding: 0;
}

/* ===== DECORATIVE DIVIDER ===== */
.divider { display: block; text-align: center; margin-bottom: 0; }
.divider .line {
  display: inline-block; width: 80pt; height: 0;
  border-top: 1px solid #F5A74C; vertical-align: middle; margin: 0 6pt;
}
.divider .diamond {
  display: inline-block; width: 7pt; height: 7pt;
  background: #BB6707; vertical-align: middle; transform: rotate(45deg);
}

/* ===== BODY — centred absolutely ===== */
.cert-body-stack {
  position: absolute;
  left: 24px; right: 24px;
  top: 50%; margin-top: -60px;   /* nudge up from true centre */
  text-align: center;
}
.sub-label {
  display: block;
  font-family: 'Plus Jakarta Sans', Arial, sans-serif;
  font-weight: 500; font-size: 9pt; color: #595F69;
  text-transform: uppercase; letter-spacing: 0.04em;
  margin: 0 0 4px;
}
.recipient-name {
  display: block;
  font-family: 'Instrument Serif', Georgia, serif;
  font-style: italic; font-weight: 400; font-size: 28pt;
  color: #17191C; margin: 0 0 6px;
}
.course-name {
  display: block;
  font-family: 'Plus Jakarta Sans', Arial, sans-serif;
  font-weight: 700; font-size: 14pt;
  color: #714109; margin: 0;
}

/* ===== FOOTER — table layout, pinned to bottom ===== */
.cert-footer {
  position: absolute;
  bottom: 14px; left: 24px; right: 24px;
  display: table; width: calc(100% - 48px);
  table-layout: fixed;
}
.date-block {
  display: table-cell; width: 130px;
  text-align: left; vertical-align: bottom;
}
.seal-badge-container {
  display: table-cell;
  text-align: center; vertical-align: bottom;
}
.seal-badge-container svg {
  width: 52px; height: 52px;
  background: #F5A74C; border: 2px solid #BB6707; border-radius: 26px;
  padding: 12px; box-sizing: border-box; display: inline-block;
}
.signature-block {
  display: table-cell; width: 130px;
  text-align: right; vertical-align: bottom;
}
.date-value {
  display: block; font-weight: 600; font-size: 8pt; color: #595F69; margin-bottom: 4px;
}
.signature-handwritten {
  display: block;
  font-family: 'Parisienne', Georgia, serif;
  font-weight: 400; font-size: 16pt; color: #714109; margin-bottom: 4px;
}
.foot-line {
  display: block; width: 100%; height: 0;
  border-top: 1px solid #ECEDEF; margin-bottom: 4px;
}
.foot-label {
  display: block; font-weight: 600; font-size: 7pt;
  color: #9CA1AB; text-transform: uppercase; letter-spacing: 0.1em;
}

/* ===== MODERN TEMPLATE overrides ===== */
.certificate {
  position: absolute; top: 0; left: 0; width: 297mm; height: 210mm;
  background: #FBF9F4; overflow: hidden;
}
.frame-pattern {
  position: absolute; top: 0; left: 0; right: 0; bottom: 0; z-index: 1;
}
.frame-mask, .border-outer, .border-inner, .corner { display: none; }
.content {
  position: absolute; top: 40px; left: 60px; right: 60px; bottom: 30px;
  z-index: 5; text-align: center; color: #1C1915;
}
.title-row { display: table; width: 100%; max-width: 700px; margin: 0 auto; }
.title-row .rule { display: table-cell; background: #A6802E; height: 1px; vertical-align: middle; }
.title {
  display: table-cell;
  font-family: 'Cinzel','Times New Roman',serif; font-weight: 600; font-size: 20pt;
  letter-spacing: 0.14em; color: #1C1915; white-space: nowrap; padding: 0 14px;
  vertical-align: middle;
}
.middle { margin: 24px auto 0; text-align: center; }
.intro { font-style: italic; font-size: 12pt; color: #5A5245; margin: 0 0 4px; display: block; }
.name {
  display: block;
  font-family: 'Cormorant Garamond',Georgia,serif; font-style: italic;
  font-weight: 600; font-size: 40pt; color: #1C1915; line-height: 1.05;
}
.name-underline { display: block; width: 400px; height: 1px; background: #A6802E; margin: 4px auto 8px; }
.body-line { display: block; font-size: 11pt; color: #5A5245; line-height: 1.5; }
.module {
  display: block;
  font-family: 'Cinzel','Times New Roman',serif; font-weight: 600; font-size: 16pt;
  letter-spacing: 0.05em; color: #7A1F2B; margin-top: 6px;
}
.score-line { margin-top: 4px; }
.score { font-weight: 600; color: #1C1915; font-style: normal; }
.footer { display: table; width: 100%; max-width: 700px; margin: 20px auto 0; }
.foot-col { display: table-cell; text-align: center; vertical-align: bottom; width: 180px; }
.seal { width: 70px; height: 88px; vertical-align: bottom; }
.foot-value {
  display: block;
  font-family: 'Cormorant Garamond',Georgia,serif; font-size: 14pt;
  font-weight: 600; color: #1C1915; min-height: 1.2em; margin-bottom: 5px;
}
.foot-rule { display: block; width: 100%; height: 1px; background: #A6802E; margin-bottom: 4px; }
.credential {
  position: absolute; left: 30px; bottom: 14px;
  font-size: 7pt; letter-spacing: 0.08em; color: #A6802E; z-index: 6;
}
"""

    # ── Build the final HTML document ─────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Certificate - {frappe.utils.escape_html(learner_name)}</title>
<style>
{_fonts}
{layout_css}
</style>
</head>
<body>
{html_body}
</body>
</html>"""

    # ── Generate PDF via wkhtmltopdf directly ─────────────────────────────────
    # We bypass frappe.utils.pdf.get_pdf because it forcibly adds:
    #   --margin-top 15mm  --margin-bottom 15mm  (even when we pass 0)
    #   --print-media-type  (triggers @media print CSS inside the template)
    #   --disable-local-file-access (breaks embedded font loading)
    # Calling wkhtmltopdf via subprocess gives us complete option control.
    import subprocess, tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as _tf:
        _tf.write(html)
        _html_path = _tf.name

    _pdf_path = _html_path.replace(".html", ".pdf")

    try:
        subprocess.check_call(
            [
                "wkhtmltopdf",
                "--page-size",        "A4",
                "--orientation",      "Landscape",
                "--margin-top",       "0",
                "--margin-right",     "0",
                "--margin-bottom",    "0",
                "--margin-left",      "0",
                "--disable-smart-shrinking",
                "--background",
                "--encoding",         "UTF-8",
                "--quiet",
                _html_path,
                _pdf_path,
            ],
            stderr=subprocess.PIPE,
        )
        with open(_pdf_path, "rb") as _pf:
            pdf_data = _pf.read()
    except subprocess.CalledProcessError as e:
        frappe.throw(f"PDF generation failed: {e.stderr.decode() if e.stderr else str(e)}")
    finally:
        for _p in (_html_path, _pdf_path):
            try:
                _os.unlink(_p)
            except Exception:
                pass

    safe_name = learner_name.replace(" ", "_")
    filename  = f"Certificate_{safe_name}_{cert_id}.pdf"

    frappe.local.response.filename    = filename
    frappe.local.response.filecontent = pdf_data
    frappe.local.response.type        = "download"


