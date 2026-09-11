import frappe

@frappe.whitelist()
def get_learner_certificates():
    user = frappe.form_dict.get("user_id") or frappe.session.user
    
    # 1. Earned Certificates
    certificates = frappe.get_all(
        "LMS Certificate",
        filters={"user": user},
        fields=["name", "certificate_id", "module", "issued_on", "certificate_pdf", "score"],
        order_by="issued_on desc"
    )
    
    results = []
    earned_modules = []
    for cert in certificates:
        title = ""
        subtitle = ""
        if cert.module:
            title = frappe.get_value("LMS Module", cert.module, "module_name") or cert.module
            subtitle = "Official Course Path Certificate"
            earned_modules.append(cert.module)
            
        # Fetch score from total_score of LMS Module Tracker
        score = cert.score or 0
        if cert.module and user:
            tracker = frappe.get_all("LMS Module Tracker", filters={"module": cert.module, "user": user}, fields=["total_score"], limit=1)
            if tracker and tracker[0].total_score is not None:
                score = tracker[0].total_score
        
        results.append({
            "id": cert.name,
            "certificateId": cert.certificate_id,
            "title": title,
            "subtitle": subtitle,
            "issueDate": cert.issued_on,
            "pdfUrl": cert.certificate_pdf,
            "score": score,
            "earned": True,
            "progress": 100
        })
        
    # 2. In-Progress Certificates
    trackers = frappe.get_all(
        "LMS Module Tracker",
        filters={
            "user": user,
            "status": ("!=", "Completed")
        },
        fields=["name", "module", "progress_percentage"]
    )
    
    for tracker in trackers:
        if tracker.module in earned_modules:
            continue
            
        enable_cert = frappe.get_value("LMS Module", tracker.module, "enable_certificate")
        if enable_cert:
            module_name = frappe.get_value("LMS Module", tracker.module, "module_name") or tracker.module
            results.append({
                "id": tracker.name,
                "certificateId": f"ongoing-{tracker.module}",
                "title": module_name,
                "subtitle": "Official Course Path Certificate",
                "issueDate": None,
                "pdfUrl": None,
                "score": 0,
                "earned": False,
                "progress": tracker.progress_percentage or 0
            })
            
    return results
