"""
Admin API for Learning Path Certificate management.
Mirrors the module certificate API in common/module_detail.py,
but operates on LMS Certificate records where learning_path is set.
"""

import frappe


@frappe.whitelist()
def get_lp_certificates(path_id):
    """
    Return all certificate records for a given learning path.
    Includes learners who have completed the path but have no cert yet (Pending rows).
    """
    try:
        lp = frappe.get_doc("LMS Learning Path", path_id)
    except Exception:
        frappe.throw(f"Learning path '{path_id}' not found.")

    validity_days = getattr(lp, "certificate_validity_period", 0) or 0

    # Fetch all existing LP certificates
    certs = frappe.get_all(
        "LMS Certificate",
        filters={"learning_path": path_id},
        fields=[
            "name", "user", "issued_on", "status", "certificate_pdf",
            "revocation_reason", "custom_revocation_reason",
            "revoked_by", "revoked_on", "pdf_status", "pdf_file_url", "score"
        ]
    )
    cert_map = {c.user: c for c in certs}

    # Fetch all Completed LP trackers so we know who *should* have a cert
    completed_trackers = frappe.get_all(
        "LMS Learning Path Tracker",
        filters={"learning_path": path_id, "status": "Completed"},
        fields=["name", "user", "total_score", "completed_on"]
    )

    certificate_data = []

    # --- Process existing certificates ---
    for cert in certs:
        try:
            user_doc = frappe.get_doc("User", cert.user)
        except Exception:
            continue

        expiry_date = None
        if cert.issued_on and validity_days > 0:
            expiry_date = frappe.utils.add_days(cert.issued_on, validity_days)

        # Compute dynamic status
        status = cert.status
        if status in ["Issued", "Reissued"]:
            if not cert.issued_on:
                status = "Pending"
            elif expiry_date and frappe.utils.getdate(frappe.utils.nowdate()) > frappe.utils.getdate(expiry_date):
                status = "Expired"

        # Score: prefer the LMS Certificate record score, fallback to LP tracker
        score = "--"
        if cert.score is not None and cert.score >= 0:
            score = f"{cert.score}"
        else:
            tracker_rec = next((t for t in completed_trackers if t.user == cert.user), None)
            if tracker_rec and tracker_rec.total_score is not None and tracker_rec.total_score >= 0:
                score = f"{tracker_rec.total_score}"

        revoked_by_name = None
        if cert.revoked_by:
            try:
                revoked_by_name = frappe.db.get_value("User", cert.revoked_by, "full_name") or cert.revoked_by
            except Exception:
                revoked_by_name = cert.revoked_by

        certificate_data.append({
            "id": cert.name,
            "certificate_id": cert.name,
            "learnerName": user_doc.full_name,
            "email": user_doc.email,
            "avatar": user_doc.user_image or None,
            "issueDate": str(cert.issued_on) if cert.issued_on else None,
            "expiryDate": str(expiry_date) if expiry_date else None,
            "status": status,
            "score": score,
            "certificate_pdf": cert.certificate_pdf or None,
            "pdf_status": cert.pdf_status or "Pending",
            "pdf_file_url": cert.pdf_file_url or None,
            "revocationReason": cert.revocation_reason,
            "customRevocationReason": cert.custom_revocation_reason,
            "revokedBy": revoked_by_name,
            "revokedOn": str(cert.revoked_on) if cert.revoked_on else None,
        })

    # --- Add "Pending" rows for completed trackers without a certificate yet ---
    for tracker in completed_trackers:
        if tracker.user in cert_map:
            continue  # Already has a cert entry above
        try:
            user_doc = frappe.get_doc("User", tracker.user)
        except Exception:
            continue

        score = f"{tracker.total_score}" if (tracker.total_score is not None and tracker.total_score >= 0) else "--"
        certificate_data.append({
            "id": f"pending-lp-{tracker.name}",
            "certificate_id": "-",
            "learnerName": user_doc.full_name,
            "email": user_doc.email,
            "avatar": user_doc.user_image or None,
            "issueDate": None,
            "expiryDate": None,
            "status": "Pending",
            "score": score,
            "certificate_pdf": None,
            "pdf_status": "Pending",
            "pdf_file_url": None,
            "revocationReason": None,
            "customRevocationReason": None,
            "revokedBy": None,
            "revokedOn": None,
        })

    # Resolve template
    template = None
    lp_template = getattr(lp, "certificate_template", None)
    if lp.enable_certificate and lp_template:
        try:
            template_doc = frappe.get_doc("LMS Certificate Template", lp_template)
            template = {
                "name": template_doc.template_name,
                "html": template_doc.html_template,
            }
        except Exception:
            pass

    # Resolve signature
    from lms.backend.api.common.certificate import get_signature_html
    signature_html = get_signature_html(learning_path_name=path_id)

    return {
        "template": template,
        "signature_html": signature_html,
        "certificates": certificate_data,
        "course_name": lp.path_name or path_id,
        "validity_days": validity_days,
    }


@frappe.whitelist()
def revoke_lp_certificates(certificate_ids, reason=None, custom_reason=None):
    """Revoke one or more LP certificates. Same logic as module revoke."""
    import json
    if isinstance(certificate_ids, str):
        certificate_ids = json.loads(certificate_ids)

    for cert_id in certificate_ids:
        # Verify this is indeed an LP certificate
        lp_val = frappe.db.get_value("LMS Certificate", cert_id, "learning_path")
        if not lp_val:
            frappe.throw(f"Certificate {cert_id} is not a Learning Path certificate.")

        frappe.db.set_value("LMS Certificate", cert_id, {
            "status": "Revoked",
            "revocation_reason": reason,
            "custom_revocation_reason": custom_reason,
            "revoked_by": frappe.session.user,
            "revoked_on": frappe.utils.now_datetime(),
        })

    frappe.db.commit()
    return True


@frappe.whitelist()
def reissue_lp_certificates(certificate_ids):
    """Reissue one or more LP certificates. Same logic as module reissue."""
    import json
    if isinstance(certificate_ids, str):
        certificate_ids = json.loads(certificate_ids)

    for cert_id in certificate_ids:
        lp_val = frappe.db.get_value("LMS Certificate", cert_id, "learning_path")
        if not lp_val:
            frappe.throw(f"Certificate {cert_id} is not a Learning Path certificate.")

        frappe.db.set_value("LMS Certificate", cert_id, {
            "issued_on": frappe.utils.nowdate(),
            "status": "Reissued",
            "revocation_reason": None,
            "custom_revocation_reason": None,
            "revoked_by": None,
            "revoked_on": None,
            "certificate_pdf": None,
            "pdf_status": "Pending",
            "pdf_file_url": None,
        })

        # Clean up old PDFs
        old_files = frappe.get_all(
            "File",
            filters={"attached_to_doctype": "LMS Certificate", "attached_to_name": cert_id}
        )
        for f in old_files:
            frappe.delete_doc("File", f.name, ignore_permissions=True)

    frappe.db.commit()
    return True
