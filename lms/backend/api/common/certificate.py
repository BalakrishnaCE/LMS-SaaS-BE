import frappe
from frappe.utils import getdate

def get_signature_html(module_name):
    signature_html = "J. Director" # default fallback
    if not module_name:
        return signature_html
        
    try:
        mod = frappe.get_doc("LMS Module", module_name)
        if mod.certificate_signature_by:
            sig_doc = frappe.get_doc("LMS Authorized Signatory", mod.certificate_signature_by)
            if sig_doc.signature_image:
                from frappe.utils.file_manager import get_file_path
                import base64
                import mimetypes
                import os
                
                file_path = get_file_path(sig_doc.signature_image)
                if os.path.exists(file_path):
                    mime_type, _ = mimetypes.guess_type(file_path)
                    with open(file_path, "rb") as f:
                        encoded_string = base64.b64encode(f.read()).decode('utf-8')
                    signature_html = f'<img src="data:{mime_type};base64,{encoded_string}" style="max-height: 45px; object-fit: contain;">'
                else:
                    signature_html = f'<img src="{sig_doc.signature_image}" style="max-height: 45px; object-fit: contain;">'
            elif sig_doc.signatory_name:
                signature_html = sig_doc.signatory_name
    except Exception:
        pass
        
    return signature_html

@frappe.whitelist(allow_guest=False)
def get_certificate_html(certificate_name):
    """Return the populated HTML certificate template for frontend rendering."""
    if not certificate_name:
        frappe.throw("Certificate name is required")

    cert = frappe.get_doc("LMS Certificate", certificate_name)

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
    
    # 1. Prioritize the Module's currently selected template so admins can dynamically change designs
    if cert.module:
        try:
            mod = frappe.get_doc("LMS Module", cert.module)
            if mod.certificate_template:
                html_template = frappe.db.get_value(
                    "LMS Certificate Template", mod.certificate_template, "html_template") or ""
        except Exception:
            pass

    # 2. Fallback to the template saved on the certificate if the module doesn't have one
    if not html_template and cert.template:
        try:
            html_template = frappe.db.get_value(
                "LMS Certificate Template", cert.template, "html_template") or ""
        except Exception:
            pass

    if not html_template:
        frappe.throw("No certificate template found for this certificate")

    issue_date = ""
    target_date = cert.issued_on or frappe.utils.today()
    if target_date:
        try:
            from frappe.utils import getdate
            issue_date = getdate(target_date).strftime("%B %d, %Y")
        except Exception:
            issue_date = str(target_date)

    score_val = str(int(cert.score)) if cert.score else "N/A"
    cert_id   = cert.name
    
    # 3. Fetch Signature
    signature_html = get_signature_html(cert.module)

    # ── Replace placeholders ──────────────────────────────────────────────────
    html_body = html_template
    html_body = html_body.replace("{{learner_name}}",   frappe.utils.escape_html(learner_name))
    html_body = html_body.replace("{{module_name}}",    frappe.utils.escape_html(module_name))
    html_body = html_body.replace("{{date}}",           frappe.utils.escape_html(issue_date))
    html_body = html_body.replace("{{score}}",          frappe.utils.escape_html(score_val))
    html_body = html_body.replace("{{certificate_id}}", frappe.utils.escape_html(cert_id))
    html_body = html_body.replace("{{signature_by}}",   signature_html)
    return {"status": "success", "html": html_body}

@frappe.whitelist(allow_guest=False)
def request_certificate_generation(certificate_name):
    if not certificate_name:
        frappe.throw("Certificate name is required")
        
    cert = frappe.get_doc("LMS Certificate", certificate_name)
    
    # If it's already generated, return the file URL
    if cert.pdf_status == "Completed" and cert.pdf_file_url:
        return {"status": "success", "message": "Already generated", "url": cert.pdf_file_url}
        
    # Queue background job
    cert.db_set("pdf_status", "Generating")
    
    frappe.enqueue(
        method="lms.backend.api.common.certificate.generate_pdf_worker",
        queue="default",
        timeout=300,
        is_async=True,
        job_name="Certificate_Generation",
        certificate_name=certificate_name
    )
    frappe.db.commit()
    
    return {"status": "queued"}

@frappe.whitelist(allow_guest=False)
def check_certificate_status(certificate_name):
    if not certificate_name:
        frappe.throw("Certificate name is required")
    cert = frappe.get_doc("LMS Certificate", certificate_name)
    return {
        "status": cert.pdf_status,
        "url": cert.pdf_file_url
    }

def generate_pdf_worker(certificate_name, **kwargs):
    import subprocess
    import tempfile
    import os
    import time
    try:
        data = get_certificate_html(certificate_name)
        html_content = data.get("html", "")
        
        cert = frappe.get_doc("LMS Certificate", certificate_name)
        
        user_name = frappe.db.get_value("User", cert.user, "full_name") or cert.user
        safe_name = "".join(c for c in user_name if c.isalnum() or c in " _-").strip().replace(" ", "_")
        filename = f"Certificate_{safe_name}.pdf"
        
        # Write HTML to temp file
        fd, tmp_html_path = tempfile.mkstemp(suffix=".html")
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(html_content)
            
        _, tmp_pdf_path = tempfile.mkstemp(suffix=".pdf")
        
        # Run playwright script
        node_script = frappe.get_app_path("lms", "..", "pdf_engine", "generate.js")
        # Resolve it absolutely
        node_script = os.path.abspath(node_script)
        
        bash_command = f"source ~/.nvm/nvm.sh && node {node_script} --input {tmp_html_path} --output {tmp_pdf_path}"
        
        result = subprocess.run(
            ["/bin/bash", "-c", bash_command],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            frappe.log_error(f"Playwright Error: {result.stderr}", "Certificate PDF Generation")
            cert.db_set("pdf_status", "Failed")
        else:
            # Read generated PDF and save as Frappe File
            with open(tmp_pdf_path, 'rb') as f:
                file_content = f.read()
                
            file_doc = frappe.get_doc({
                "doctype": "File",
                "file_name": filename,
                "attached_to_doctype": "LMS Certificate",
                "attached_to_name": certificate_name,
                "attached_to_field": "pdf_file_url",
                "content": file_content,
                "is_private": 1
            })
            file_doc.save(ignore_permissions=True)
            
            cert.db_set("pdf_status", "Completed")
            cert.db_set("pdf_file_url", file_doc.file_url)
            
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Certificate PDF Worker Error")
        cert = frappe.get_doc("LMS Certificate", certificate_name)
        cert.db_set("pdf_status", "Failed")
        
    finally:
        frappe.db.commit()
        if 'tmp_html_path' in locals() and os.path.exists(tmp_html_path):
            os.remove(tmp_html_path)
        if 'tmp_pdf_path' in locals() and os.path.exists(tmp_pdf_path):
            os.remove(tmp_pdf_path)
