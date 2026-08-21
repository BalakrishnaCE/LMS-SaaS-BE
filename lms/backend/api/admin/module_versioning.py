import frappe
import json

@frappe.whitelist(allow_guest=False)
def get_module_version_preview(module_id, version):
    """
    Returns the parsed content_snapshot JSON for a specific module version.
    Used for previewing older versions before restoring.
    """
    if not frappe.has_permission("LMS Module", "read", module_id):
        frappe.throw("Not permitted", frappe.PermissionError)
        
    version_doc = frappe.db.get_value(
        "LMS Module Version",
        {"parent": module_id, "version": version},
        "content_snapshot"
    )
    
    if not version_doc:
        return {"lessons": []}
        
    try:
        snapshot = json.loads(version_doc)
        return snapshot
    except Exception as e:
        frappe.log_error(f"Failed to parse content_snapshot for {module_id} version {version}: {str(e)}")
        return {"lessons": []}
