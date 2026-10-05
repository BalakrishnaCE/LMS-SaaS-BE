import frappe
import json
from frappe.utils import today


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot helpers
# ─────────────────────────────────────────────────────────────────────────────

@frappe.whitelist(allow_guest=False)
def get_learning_path_version_preview(path_id, version):
    """
    Returns the parsed content_snapshot JSON for a specific Learning Path version.
    Used for previewing older versions before restoring.
    """
    if not frappe.has_permission("LMS Learning Path", "read", path_id):
        frappe.throw("Not permitted", frappe.PermissionError)
        
    version_doc = frappe.db.get_value(
        "LMS Learning Path Version",
        {"parent": path_id, "version": version},
        "content_snapshot"
    )
    
    if not version_doc:
        return {}
        
    try:
        snapshot = json.loads(version_doc)
        return snapshot
    except Exception as e:
        frappe.log_error(f"Failed to parse content_snapshot for {path_id} version {version}: {str(e)}")
        return {}


def _build_learning_path_snapshot(path_doc):
    """
    Builds a complete JSON-serialisable snapshot of an LMS Learning Path.
    Captures:
      - path-level settings (name, description, image, flags, status)
      - ordered list of module IDs (courses child table)
    """
    snapshot = {
        "path_settings": {
            "path_name": path_doc.path_name,
            "description": path_doc.description or "",
            "image": path_doc.image or "",
            "is_mandatory": int(path_doc.is_mandatory or 0),
            "is_sequential": int(path_doc.is_sequential or 0),
            "enable_certificate": int(path_doc.enable_certificate or 0),
            "enable_discussion": int(getattr(path_doc, "enable_discussion", 0) or 0),
            "complete_all_modules": int(path_doc.complete_all_modules or 0),
            "is_score_required": int(path_doc.is_score_required or 0),
            "complete_all_interactions": int(path_doc.complete_all_interactions or 0),
            "duration": path_doc.duration or 0,
            "status": path_doc.status or "Draft",
        },
        "modules": [
            {
                "module": c.module,
                "sequence_order": c.sequence_order,
            }
            for c in sorted(
                path_doc.get("courses", []),
                key=lambda c: c.sequence_order or 0
            )
            if c.module
        ],
    }
    return snapshot


def _apply_learning_path_snapshot(path_id, snapshot):
    """
    Applies a snapshot back onto an LMS Learning Path.
    Handles potential rename (path_name change) the same way module
    versioning does — via frappe.rename_doc.
    Returns the final path_id (may differ if rename occurred).
    """
    path_settings = snapshot.get("path_settings", {})
    if path_settings:
        path = frappe.get_doc("LMS Learning Path", path_id)
        old_name = path.name
        new_name = path_settings.get("path_name")

        # Rename if the path name changed
        if new_name and old_name != new_name:
            if frappe.db.exists("LMS Learning Path", new_name):
                # Destination already exists — skip rename, keep old ID
                path_settings.pop("path_name", None)
            else:
                actual_new_name = frappe.rename_doc(
                    "LMS Learning Path", old_name, new_name, force=True
                )
                path_id = actual_new_name
                path = frappe.get_doc("LMS Learning Path", path_id)

        # Apply all settings fields
        for field, value in path_settings.items():
            if path.meta.has_field(field):
                setattr(path, field, value)

        # Rebuild courses child table
        path.set("courses", [])
        for idx, module_row in enumerate(snapshot.get("modules", [])):
            module_name = module_row.get("module")
            if not module_name:
                continue
            if not frappe.db.exists("LMS Module", module_name):
                frappe.log_error(
                    f"Module '{module_name}' no longer exists; skipped in Learning Path restore."
                )
                continue
            path.append("courses", {
                "module": module_name,
                "sequence_order": module_row.get("sequence_order", idx + 1),
            })

        path.save(ignore_permissions=True)

    return path_id


# ─────────────────────────────────────────────────────────────────────────────
# Public whitelisted API
# ─────────────────────────────────────────────────────────────────────────────

@frappe.whitelist(allow_guest=False)
def create_learning_path_version(path_id, description=""):
    """
    Creates a new version entry in the learning path's version_history.
    Snapshots the current path settings + module list so it can be restored later.
    """
    if not frappe.has_permission("LMS Learning Path", "write", doc=path_id):
        frappe.throw("Not permitted", frappe.PermissionError)

    path = frappe.get_doc("LMS Learning Path", path_id)
    version_history = path.get("version_history", [])

    # Reset is_current on all existing versions
    for v in version_history:
        v.is_current = 0

    # Determine next version number
    if not version_history:
        new_version = "v1.0"
    else:
        max_major = 1
        max_minor = -1
        for v in version_history:
            try:
                parts = v.version.lstrip("v").split(".")
                maj = int(parts[0])
                min_ = int(parts[1]) if len(parts) > 1 else 0
                if maj > max_major or (maj == max_major and min_ > max_minor):
                    max_major = maj
                    max_minor = min_
            except Exception:
                pass
        new_version = f"v{max_major}.{max(max_minor + 1, 0)}"

    # Build snapshot
    snapshot = _build_learning_path_snapshot(path)
    snapshot_json = json.dumps(snapshot, default=str)

    # Author info
    current_user = frappe.session.user
    author_name = (
        frappe.db.get_value("User", current_user, "full_name") or current_user
    )

    path.append("version_history", {
        "version": new_version,
        "is_current": 1,
        "description": description or f"Version {new_version}",
        "date": today(),
        "author": current_user,
        "author_name": author_name,
        "content_snapshot": snapshot_json,
    })

    path.save(ignore_permissions=True)

    # Store snapshot in a separate DB write to keep it out of the dirty check
    new_row = next(v for v in path.version_history if v.version == new_version)
    frappe.db.set_value(
        "LMS Learning Path Version",
        new_row.name,
        "content_snapshot",
        snapshot_json,
        update_modified=False,
    )
    frappe.db.commit()

    return {"message": "success", "new_version": new_version}


@frappe.whitelist(allow_guest=False)
def restore_learning_path_version(path_id, version):
    """
    Restores a learning path to a previous version snapshot.
    Returns the (possibly renamed) path_id after restoration.
    """
    if not frappe.has_permission("LMS Learning Path", "write", doc=path_id):
        frappe.throw("Not permitted", frappe.PermissionError)

    path = frappe.get_doc("LMS Learning Path", path_id)
    version_history = path.get("version_history", [])

    target_v = next((v for v in version_history if v.version == version), None)
    if not target_v:
        frappe.throw(f"Version {version} not found in history.")

    # Apply snapshot
    new_path_id = path_id
    if target_v.content_snapshot:
        try:
            snapshot = json.loads(target_v.content_snapshot)
            new_path_id = _apply_learning_path_snapshot(path_id, snapshot)
        except Exception as e:
            frappe.log_error(f"Failed to restore Learning Path snapshot for version {version}: {str(e)}")
            frappe.throw(f"Failed to restore content: {str(e)}")

    # Reload and update is_current flags
    path = frappe.get_doc("LMS Learning Path", new_path_id)
    version_history = path.get("version_history", [])
    target_v = next((v for v in version_history if v.version == version), None)

    for v in version_history:
        v.is_current = 1 if (target_v and v.name == target_v.name) else 0

    path.save(ignore_permissions=True)
    return {"message": "success", "restored_version": version, "new_id": path.name}


@frappe.whitelist(allow_guest=False)
def has_learning_path_unpublished_changes(path_id):
    """
    Checks whether the current learning path differs from the latest published
    version snapshot (settings + module list).
    """
    path = frappe.get_doc("LMS Learning Path", path_id)
    versions = path.get("version_history", [])

    if not versions:
        return {"has_changes": True}

    latest_v = next((v for v in versions if v.is_current), versions[-1])

    try:
        if latest_v.content_snapshot:
            old_snapshot = json.loads(latest_v.content_snapshot)
            # Exclude status/certificate/discussion from change detection
            for field in ("status", "enable_certificate", "enable_discussion"):
                old_snapshot.get("path_settings", {}).pop(field, None)

            current_snapshot = json.loads(
                json.dumps(_build_learning_path_snapshot(path), default=str)
            )
            for field in ("status", "enable_certificate", "enable_discussion"):
                current_snapshot.get("path_settings", {}).pop(field, None)

            return {"has_changes": old_snapshot != current_snapshot}
    except Exception as e:
        frappe.log_error(f"Error in has_learning_path_unpublished_changes: {str(e)}")
        return {"has_changes": True}

    return {"has_changes": True}
