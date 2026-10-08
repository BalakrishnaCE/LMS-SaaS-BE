import frappe
from frappe.utils import getdate, add_days, nowdate

@frappe.whitelist()
def get_learner_certificates():
    user = frappe.form_dict.get("user_id") or frappe.session.user
    
    # 1. Existing Certificates (Issued, Revoked, Expired, Pending if no issued_on)
    certificates = frappe.get_all(
        "LMS Certificate",
        filters={"user": user, "docstatus": 1} if hasattr(frappe.get_meta("LMS Certificate"), "is_submittable") and frappe.get_meta("LMS Certificate").is_submittable else {"user": user},
        fields=["name", "module", "issued_on", "status", "certificate_pdf", "score", "template", "is_claimed"],
        order_by="issued_on desc"
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
            "certificateId": cert.name,
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
            passing_score = mod.certificate_passing_percentage or 60
            is_completed = (tracker.status == "Completed")
            
            if is_completed:
                if (tracker.total_score or 0) < passing_score:
                    # Completed but failed to meet certificate criteria
                    continue
                else:
                    status = "Pending"
            else:
                status = "Ongoing"
            
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
            
    # 3. Learning Path Certificates (completed paths with enable_certificate=True)
    lp_trackers = frappe.get_all(
        "LMS Learning Path Tracker",
        filters={"user": user},
        fields=["name", "learning_path", "status", "progress_percentage", "total_score", "completed_on"]
    )
    
    for lp_tracker in lp_trackers:
        if not lp_tracker.learning_path:
            continue
        
        try:
            lp = frappe.get_doc("LMS Learning Path", lp_tracker.learning_path)
        except Exception:
            continue
        
        if not lp.enable_certificate:
            continue
        
        # Get path name and template
        lp_title = lp.path_name or lp_tracker.learning_path
        lp_template = getattr(lp, 'certificate_template', None)
        
        # Count module certificates earned within this path
        path_courses = frappe.get_all(
            "LMS Learning Path Course",
            filters={"parent": lp_tracker.learning_path},
            fields=["module"]
        )
        module_ids = [pc.module for pc in path_courses]
        module_certs_earned = 0
        if module_ids:
            module_certs_earned = frappe.db.count(
                "LMS Certificate",
                filters={"user": user, "module": ("in", module_ids), "status": ("in", ["Issued", "Reissued"])}
            )
        
        # Fetch preview image from LP certificate template
        lp_preview_image = None
        if lp_template:
            try:
                lp_preview_image = frappe.db.get_value("LMS Certificate Template", lp_template, "preview_image")
                if not lp_preview_image:
                    lp_preview_image = frappe.db.get_value("LMS Certificate Template", lp_template, "thumbnail")
            except Exception:
                pass
        
        is_lp_completed = lp_tracker.status == "Completed"
        lp_progress = lp_tracker.progress_percentage or 0
        lp_score = lp_tracker.total_score if (lp_tracker.total_score is not None and lp_tracker.total_score >= 0) else None
        
        if is_lp_completed:
            lp_status = "Issued"
            lp_earned = True
        elif lp_progress > 0:
            lp_status = "Ongoing"
            lp_earned = False
        else:
            continue  # Not started — skip
        
        completed_on_str = None
        if is_lp_completed and lp_tracker.completed_on:
            try:
                completed_on_str = lp_tracker.completed_on.strftime("%Y-%m-%d")
            except Exception:
                completed_on_str = str(lp_tracker.completed_on)[:10]
        
        results.append({
            "id": f"lp-tracker-{lp_tracker.name}",
            "certificateId": f"lp-{lp_tracker.learning_path}",
            "title": lp_title,
            "subtitle": "Learning Path Certificate",
            "issueDate": completed_on_str,
            "pdfUrl": None,
            "score": lp_score,
            "status": lp_status,
            "earned": lp_earned,
            "progress": lp_progress,
            "previewImage": lp_preview_image,
            "isClaimed": False,
            "sourceType": "Learning Path",
            "sourceId": lp_tracker.learning_path,
            "moduleCertificatesEarned": module_certs_earned,
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
        frappe.db.set_value("LMS Certificate", certificate_name, "is_claimed", 1)
        frappe.db.commit()
        
    return {"status": "success"}
