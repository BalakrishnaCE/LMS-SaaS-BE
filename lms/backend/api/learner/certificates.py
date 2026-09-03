import frappe

@frappe.whitelist()
def get_learner_certificates():
    user = frappe.session.user
    certificates = frappe.get_all(
        "LMS Certificate",
        filters={"user": user},
        fields=["name", "certificate_id", "module", "issued_on", "certificate_pdf", "score"],
        order_by="issued_on desc"
    )
    
    results = []
    for cert in certificates:
        title = ""
        subtitle = ""
        if cert.module:
            title = frappe.get_value("LMS Module", cert.module, "module_name") or cert.module
            subtitle = "Official Course Path Certificate"
        
        results.append({
            "id": cert.name,
            "certificateId": cert.certificate_id,
            "title": title,
            "subtitle": subtitle,
            "issueDate": cert.issued_on,
            "pdfUrl": cert.certificate_pdf,
            "score": cert.score or 0
        })
        
    return results
