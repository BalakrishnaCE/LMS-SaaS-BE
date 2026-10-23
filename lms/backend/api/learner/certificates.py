import frappe
from frappe.utils import getdate, add_days, nowdate

def check_module_has_assessments(module_name):
    if not module_name:
        return False
    return bool(frappe.db.sql("""
        SELECT 1
        FROM `tabLMS Module Lesson Child` ml
        JOIN `tabLMS Lesson Chapter` lc ON lc.parent = ml.lesson
        JOIN `tabLMS Chapter Content` cc ON cc.parent = lc.chapter
        WHERE ml.parent = %s AND cc.content_type IN ('LMS Quiz Content', 'LMS Assessment Content')
        LIMIT 1
    """, (module_name,)))

def check_learning_path_has_assessments(lp_name):
    if not lp_name:
        return False
    return bool(frappe.db.sql("""
        SELECT 1
        FROM `tabLMS Learning Path Course` lpc
        JOIN `tabLMS Module Lesson Child` ml ON ml.parent = lpc.module
        JOIN `tabLMS Lesson Chapter` lc ON lc.parent = ml.lesson
        JOIN `tabLMS Chapter Content` cc ON cc.parent = lc.chapter
        WHERE lpc.parent = %s AND cc.content_type IN ('LMS Quiz Content', 'LMS Assessment Content')
        LIMIT 1
    """, (lp_name,)))

@frappe.whitelist()
def get_learner_certificates():
    user = frappe.form_dict.get("user_id") or frappe.session.user
    
    # 1. Existing Certificates (Issued, Revoked, Expired, Pending if no issued_on)
    certificates = frappe.get_all(
        "LMS Certificate",
        filters={"user": user, "docstatus": 1} if hasattr(frappe.get_meta("LMS Certificate"), "is_submittable") and frappe.get_meta("LMS Certificate").is_submittable else {"user": user},
        fields=["name", "module", "learning_path", "issued_on", "status", "certificate_pdf", "score", "template", "is_claimed"],
        order_by="issued_on desc"
    )
    
    results = []
    processed_modules = []
    processed_learning_paths = []
    
    for cert in certificates:
        if cert.module:
            if cert.module in processed_modules:
                continue
                
            title = ""
            subtitle = "Official Course Path Certificate"
            validity_days = 0
            mod_template = None
            
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
            has_assessments = check_module_has_assessments(cert.module) or (cert.score is not None and cert.score > 0)
            score = None
            if has_assessments:
                if cert.module and user:
                    tracker = frappe.get_all("LMS Module Tracker", filters={"module": cert.module, "user": user}, fields=["total_score"], limit=1)
                    if tracker and tracker[0].total_score is not None and tracker[0].total_score > 0:
                        score = tracker[0].total_score
                if score is None and cert.score is not None and cert.score > 0:
                    score = cert.score
                    
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
                "hasAssessments": has_assessments,
                "status": status,
                "earned": status in ["Issued", "Reissued"],
                "progress": 100,
                "previewImage": preview_image,
                "isClaimed": bool(cert.is_claimed),
                "sourceType": "Module",
                "moduleId": cert.module
            })

        elif getattr(cert, "learning_path", None):
            lp_id = cert.learning_path
            if lp_id in processed_learning_paths:
                continue
                
            title = lp_id
            subtitle = "Learning Path Certificate"
            validity_days = 0
            lp_template = None
            
            try:
                lp = frappe.get_doc("LMS Learning Path", lp_id)
                title = lp.path_name or lp_id
                validity_days = lp.certificate_validity_period or 0
                lp_template = lp.certificate_template
            except Exception:
                pass
            processed_learning_paths.append(lp_id)
                
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
                            
            # Fetch score
            has_lp_assessments = check_learning_path_has_assessments(lp_id) or (cert.score is not None and cert.score > 0)
            score = None
            lp_progress = 100
            if user:
                tracker = frappe.get_all("LMS Learning Path Tracker", filters={"learning_path": lp_id, "user": user}, fields=["total_score", "progress_percentage"], limit=1)
                if tracker:
                    if has_lp_assessments and tracker[0].total_score is not None and tracker[0].total_score > 0:
                        score = tracker[0].total_score
                    if status not in ["Issued", "Reissued"]:
                        lp_progress = tracker[0].progress_percentage or 0
            if score is None and has_lp_assessments and cert.score is not None and cert.score > 0:
                score = cert.score

            # Count module certificates earned in this path
            path_courses = frappe.get_all(
                "LMS Learning Path Course",
                filters={"parent": lp_id},
                fields=["module"]
            )
            module_ids = [pc.module for pc in path_courses]
            module_certs_earned = 0
            if module_ids:
                module_certs_earned = frappe.db.count(
                    "LMS Certificate",
                    filters={"user": user, "module": ("in", module_ids), "status": ("in", ["Issued", "Reissued"])}
                )
                    
            # Fetch Preview Image
            preview_image = None
            template_name = lp_template or cert.template
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
                "pdfUrl": cert.name,
                "score": score,
                "hasAssessments": has_lp_assessments,
                "status": status,
                "earned": status in ["Issued", "Reissued"],
                "progress": lp_progress,
                "previewImage": preview_image,
                "isClaimed": bool(cert.is_claimed),
                "sourceType": "Learning Path",
                "sourceId": lp_id,
                "moduleCertificatesEarned": module_certs_earned,
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
            has_assessments = check_module_has_assessments(tracker.module)
            
            if is_completed:
                if has_assessments and (tracker.total_score or 0) < passing_score:
                    # Completed but failed to meet certificate criteria
                    continue
                else:
                    status = "Pending"
            else:
                status = "Ongoing"
            
            score = tracker.total_score if (has_assessments and is_completed and tracker.total_score is not None and tracker.total_score > 0) else None
            
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
                "score": score,
                "hasAssessments": has_assessments,
                "status": status,
                "earned": False,
                "progress": tracker.progress_percentage or 0,
                "previewImage": preview_image,
                "isClaimed": False,
                "sourceType": "Module"
            })
            
    # 3. Learning Path Trackers without Certificates (Ongoing OR Pending)
    lp_trackers = frappe.get_all(
        "LMS Learning Path Tracker",
        filters={"user": user},
        fields=["name", "learning_path", "status", "progress_percentage", "total_score", "completed_on"]
    )
    
    for lp_tracker in lp_trackers:
        if not lp_tracker.learning_path or lp_tracker.learning_path in processed_learning_paths:
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
        
        has_lp_assessments = check_learning_path_has_assessments(lp_tracker.learning_path)
        passing_score = getattr(lp, 'certificate_passing_percentage', None) or 0
        is_lp_completed = lp_tracker.status == "Completed"
        lp_progress = lp_tracker.progress_percentage or 0
        lp_score = lp_tracker.total_score if (has_lp_assessments and lp_tracker.total_score is not None and lp_tracker.total_score > 0) else None
        
        if is_lp_completed:
            if has_lp_assessments and passing_score > 0 and lp_score is not None and lp_score < passing_score:
                continue
            lp_status = "Pending"
        elif lp_progress > 0:
            lp_status = "Ongoing"
        else:
            continue  # Not started — skip
        
        results.append({
            "id": f"ongoing-lp-{lp_tracker.name}",
            "certificateId": f"ongoing-lp-{lp_tracker.learning_path}",
            "title": lp_title,
            "subtitle": "Learning Path Certificate",
            "issueDate": None,
            "pdfUrl": None,
            "score": lp_score,
            "hasAssessments": has_lp_assessments,
            "status": lp_status,
            "earned": False,
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

@frappe.whitelist()
def get_learning_path_certificates(learning_path):
    user = frappe.form_dict.get("user_id") or frappe.session.user
    user_name = frappe.db.get_value("User", user, "full_name") or user
    
    try:
        issuer_name = frappe.db.get_single_value("LMS Settings", "brand_name") or "LEARNING ACADEMY"
    except Exception:
        issuer_name = "LEARNING ACADEMY"
    
    path_courses = frappe.get_all(
        "LMS Learning Path Course",
        filters={"parent": learning_path},
        fields=["module"]
    )
    module_ids = [pc.module for pc in path_courses]
    
    module_certs = []
    if module_ids:
        certs = frappe.get_all(
            "LMS Certificate",
            filters={"user": user, "module": ("in", module_ids), "status": ("in", ["Issued", "Reissued"])},
            fields=["name", "module", "issued_on", "status", "score", "is_claimed"]
        )
        
        for cert in certs:
            # Verify module tracker is genuinely completed
            tracker = frappe.db.get_value(
                "LMS Module Tracker",
                {"user": user, "module": cert.module},
                ["status", "progress_percentage"],
                as_dict=True
            )
            if not tracker or tracker.status != "Completed" or (tracker.progress_percentage or 0) < 100:
                # Automatically revoke certificate if tracker is not completed
                frappe.db.set_value("LMS Certificate", cert.name, {
                    "status": "Revoked",
                    "revocation_reason": "Certification requirements changed",
                    "custom_revocation_reason": "Module requirements not met.",
                    "revoked_on": frappe.utils.now_datetime()
                })
                continue

            module_name = frappe.db.get_value("LMS Module", cert.module, "module_name") or cert.module
            
            # Fetch signature name for this module
            signature_name = "Learning & Development"
            try:
                sig_by = frappe.db.get_value("LMS Module", cert.module, "certificate_signature_by")
                if sig_by:
                    sig_name = frappe.db.get_value("LMS Authorized Signatory", sig_by, "signatory_name")
                    if sig_name:
                        signature_name = sig_name
            except Exception:
                pass
                
            module_certs.append({
                "id": cert.name,
                "title": module_name,
                "issueDate": cert.issued_on,
                "pdfUrl": cert.name,
                "score": cert.score,
                "isClaimed": bool(cert.is_claimed),
                "issuerName": issuer_name,
                "authorizationName": signature_name
            })
    lp_tracker = frappe.get_value(
        "LMS Learning Path Tracker",
        {"user": user, "learning_path": learning_path},
        ["status", "completed_on", "total_score", "name"],
        as_dict=True
    )
    
    lp_cert = None
    if lp_tracker and lp_tracker.status == "Completed":
        lp_name = frappe.db.get_value("LMS Learning Path", learning_path, "path_name") or learning_path
        completed_on_str = None
        if lp_tracker.completed_on:
            try:
                completed_on_str = lp_tracker.completed_on.strftime("%Y-%m-%d")
            except Exception:
                completed_on_str = str(lp_tracker.completed_on)[:10]
                
        lp_cert = {
            "id": f"lp-tracker-{lp_tracker.name}",
            "title": lp_name,
            "issueDate": completed_on_str,
            "pdfUrl": None,
            "score": lp_tracker.total_score if (lp_tracker.total_score is not None and lp_tracker.total_score >= 0) else None,
            "issuerName": issuer_name,
            "authorizationName": "Learning & Development"
        }
        
    return {
        "userName": user_name,
        "moduleCertificates": module_certs,
        "learningPathCertificate": lp_cert
    }
