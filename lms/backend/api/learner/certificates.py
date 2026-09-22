import frappe
from frappe.utils import getdate, add_days, nowdate

@frappe.whitelist()
def get_learner_certificates():
    user = frappe.form_dict.get("user_id") or frappe.session.user
    
    # 1. Existing Certificates (Issued, Revoked, Expired, Pending if no issued_on)
    certificates = frappe.get_all(
        "LMS Certificate",
        filters={"user": user},
        fields=["name", "certificate_id", "module", "issued_on", "status", "certificate_pdf", "score", "template", "is_claimed"],
        order_by="status asc, issued_on desc"
    )
    
    results = []
    processed_modules = []
    
    for cert in certificates:
        if cert.module in processed_modules:
            continue
            
        title = ""
        subtitle = "Official Course Path Certificate"
        validity_days = 0
        mod_template = None
        
        if cert.module:
            try:
                mod = frappe.get_doc("LMS Module", cert.module)
                title = mod.module_name
                validity_days = mod.certificate_validity_period or 0
                mod_template = mod.certificate_template
            except Exception:
                title = cert.module
            processed_modules.append(cert.module)
            
        # Determine Status
        status = cert.status
            
        expiry_date = None
        
        if status in ["Issued", "Reissued"]:
            if not cert.issued_on:
                status = "Pending"
            else:
                if validity_days > 0:
                    expiry_date = add_days(cert.issued_on, validity_days)
                    if getdate(nowdate()) > getdate(expiry_date):
                        status = "Expired"
                        
        # Fetch score from total_score of LMS Module Tracker
        score = cert.score or 0
        if cert.module and user:
            tracker = frappe.get_all("LMS Module Tracker", filters={"module": cert.module, "user": user}, fields=["total_score"], limit=1)
            if tracker and tracker[0].total_score is not None:
                score = tracker[0].total_score
                
        # Fetch Preview Image
        preview_image = None
        template_name = mod_template or cert.template
        if template_name:
            try:
                preview_image = frappe.db.get_value("LMS Certificate Template", template_name, "preview_image")
                if not preview_image:
                    preview_image = frappe.db.get_value("LMS Certificate Template", template_name, "thumbnail")
            except Exception:
                pass
        
        results.append({
            "id": cert.name,
            "certificateId": cert.certificate_id or cert.name,
            "title": title,
            "subtitle": subtitle,
            "issueDate": cert.issued_on,
            "pdfUrl": cert.name, # Use name as the ID for fetching HTML later
            "score": score,
            "status": status,
            "earned": status in ["Issued", "Reissued"],
            "progress": 100,
            "previewImage": preview_image,
            "isClaimed": bool(cert.is_claimed),
            "sourceType": "Module",
            "moduleId": cert.module
        })
        
    # 2. Trackers without Certificates (Ongoing OR Pending if completed but no certificate doc)
    trackers = frappe.get_all(
        "LMS Module Tracker",
        filters={"user": user},
        fields=["name", "module", "progress_percentage", "status", "total_score"]
    )
    
    for tracker in trackers:
        if tracker.module in processed_modules:
            continue
            
        enable_cert = False
        module_name = tracker.module
        mod_template = None
        try:
            mod = frappe.get_doc("LMS Module", tracker.module)
            if mod.status != "Published":
                continue
            enable_cert = mod.enable_certificate
            module_name = mod.module_name
            mod_template = mod.certificate_template
        except Exception:
            pass
            
        if enable_cert:
            is_completed = (tracker.status == "Completed")
            status = "Pending" if is_completed else "Ongoing"
            
            preview_image = None
            if mod_template:
                try:
                    preview_image = frappe.db.get_value("LMS Certificate Template", mod_template, "preview_image")
                    if not preview_image:
                        preview_image = frappe.db.get_value("LMS Certificate Template", mod_template, "thumbnail")
                except Exception:
                    pass
            
            results.append({
                "id": tracker.name,
                "certificateId": f"ongoing-{tracker.module}",
                "title": module_name,
                "subtitle": "Official Course Path Certificate",
                "issueDate": None,
                "pdfUrl": None,
                "score": tracker.total_score if is_completed else 0,
                "status": status,
                "earned": False,
                "progress": tracker.progress_percentage or 0,
                "previewImage": preview_image,
                "isClaimed": False,
                "sourceType": "Module"
            })
            
    return results

@frappe.whitelist()
def claim_certificate(certificate_name):
    if not certificate_name:
        frappe.throw("Certificate name is required")
        
    user = frappe.form_dict.get("user_id") or frappe.session.user
    cert = frappe.get_doc("LMS Certificate", certificate_name)
    
    if cert.user != user:
        frappe.throw("Not authorized to claim this certificate")
        
    if not cert.is_claimed:
        cert.is_claimed = 1
        cert.save(ignore_permissions=True)
        frappe.db.commit()
        
    return {"status": "success"}
