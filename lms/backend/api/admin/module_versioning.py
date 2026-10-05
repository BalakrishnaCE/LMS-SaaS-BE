import frappe
import json
from frappe.utils import today

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


def _build_content_snapshot(module_doc):
    """
    Builds a complete JSON-serialisable snapshot of all content for a module.
    Captures: module settings + lessons + chapters + chapter content blocks.
    """
    snapshot = {
        "module_settings": {
            "module_name": module_doc.module_name,
            "description": module_doc.description or "",
            "image": module_doc.image or "",
            "is_mandatory": int(module_doc.is_mandatory or 0),
            "is_sequential": int(getattr(module_doc, "is_sequential", 0)),
            "allow_skip": int(getattr(module_doc, "allow_skip", 0)),
            "enable_ai_flashcards": int(getattr(module_doc, "enable_ai_flashcards", 0)),
        },
        "lessons": []
    }

    lesson_names = [l.lesson for l in module_doc.get("lessons", []) if l.lesson]
    for lesson_name in lesson_names:
        try:
            lesson = frappe.get_doc("LMS Lesson", lesson_name)
            lesson_data = {
                "name": lesson.name,
                "lesson_name": lesson.lesson_name,
                "description": lesson.description or "",
                "chapters": []
            }

            chapter_links = frappe.db.get_all(
                "LMS Lesson Chapter",
                filters={"parent": lesson_name},
                fields=["chapter", "idx"],
                order_by="idx asc"
            )
            for cl in chapter_links:
                if not cl.chapter:
                    continue
                try:
                    chapter = frappe.get_doc("LMS Chapter", cl.chapter)
                    chapter_data = {
                        "name": chapter.name,
                        "title": chapter.title,
                        "contents": []
                    }
                    content_rows = frappe.db.get_all(
                        "LMS Chapter Content",
                        filters={"parent": chapter.name, "parenttype": "LMS Chapter"},
                        fields=["name", "content_type", "content_data", "order", "content_reference"],
                        order_by="`order` asc"
                    )
                    for row in content_rows:
                        # Fetch the actual content document
                        actual_content = {}
                        if row.content_type and row.content_reference:
                            try:
                                doc = frappe.get_doc(row.content_type, row.content_reference)
                                # Exclude system fields
                                actual_content = {k: v for k, v in doc.as_dict().items() if k not in ["name", "creation", "modified", "modified_by", "owner", "docstatus", "idx"]}
                            except Exception:
                                pass
                        
                        chapter_data["contents"].append({
                            "name": row.name,
                            "content_type": row.content_type,
                            "content_data": row.content_data or "",
                            "order": row.order,
                            "content_reference": row.content_reference or "",
                            "actual_content": actual_content
                        })
                    lesson_data["chapters"].append(chapter_data)
                except Exception:
                    pass
            snapshot["lessons"].append(lesson_data)
        except Exception:
            pass

    return snapshot


def _apply_content_snapshot(module_id, snapshot):
    """
    Applies a content snapshot to restore the module's content to a previous state.
    Updates lesson/chapter/content records in-place using the stored snapshot.
    Returns the module_id (which may have changed if renamed).
    """
    # Restore module-level settings
    module_settings = snapshot.get("module_settings", {})
    if module_settings:
        module = frappe.get_doc("LMS Module", module_id)
        old_name = module.name
        new_name = module_settings.get("module_name")
        
        # If the name changed, we must rename the document in Frappe
        if new_name and old_name != new_name:
            if frappe.db.exists("LMS Module", new_name):
                # We can't rename it back if another module took the name, just skip renaming the ID
                module_settings.pop("module_name", None)
            else:
                actual_new_name = frappe.rename_doc("LMS Module", old_name, new_name, force=True)
                module_id = actual_new_name
                module = frappe.get_doc("LMS Module", module_id)
                
        for field, value in module_settings.items():
            if module.meta.has_field(field):
                setattr(module, field, value)
                
        # Rebuild lessons child table
        module.set("lessons", [])
        for idx, lesson_data in enumerate(snapshot.get("lessons", [])):
            if lesson_data.get("name"):
                module.append("lessons", {
                    "lesson": lesson_data.get("name"),
                    "order": idx + 1
                })
                
        module.flags.ignore_trackers = True
        module.flags.ignore_links = True
        module.save(ignore_permissions=True, ignore_version=True)

    # Restore lessons, chapters, and content blocks
    for lesson_data in snapshot.get("lessons", []):
        lesson_name = lesson_data.get("name")
        if not lesson_name:
            continue
        try:
            lesson = frappe.get_doc("LMS Lesson", lesson_name)
        except frappe.DoesNotExistError:
            continue
            
        try:
            lesson_changed = False
            if lesson.lesson_name != lesson_data.get("lesson_name", lesson.lesson_name):
                lesson.lesson_name = lesson_data.get("lesson_name", lesson.lesson_name)
                lesson_changed = True
            
            desc = lesson_data.get("description", "")
            if (lesson.description or "") != desc:
                lesson.description = desc
                lesson_changed = True
            
            # Rebuild chapters child table
            original_chapters = [(c.chapter, c.order) for c in lesson.get("chapters", [])]
            new_chapters = [(c.get("name"), idx + 1) for idx, c in enumerate(lesson_data.get("chapters", [])) if c.get("name")]
            
            if original_chapters != new_chapters:
                lesson.set("chapters", [])
                for chap_name, order in new_chapters:
                    lesson.append("chapters", {
                        "chapter": chap_name,
                        "order": order
                    })
                lesson_changed = True
                
            if lesson_changed:
                lesson.flags.ignore_trackers = True
                lesson.flags.ignore_links = True
                lesson.save(ignore_permissions=True, ignore_version=True)
        except Exception:
            pass

        for chapter_data in lesson_data.get("chapters", []):
            chapter_name = chapter_data.get("name")
            if not chapter_name:
                continue
            try:
                chapter = frappe.get_doc("LMS Chapter", chapter_name)
            except frappe.DoesNotExistError:
                continue
                
            try:
                chapter_changed = False
                if chapter.title != chapter_data.get("title", chapter.title):
                    chapter.title = chapter_data.get("title", chapter.title)
                    chapter_changed = True

                # Build a map of existing content rows by name
                existing_map = {row.name: row for row in chapter.get("contents", [])}
                snapshot_names = {c["name"] for c in chapter_data.get("contents", []) if c.get("name")}

                # Remove rows that don't exist in the snapshot
                original_len = len(chapter.get("contents", []))
                chapter.set("contents", [row for row in chapter.get("contents", []) if row.name in snapshot_names])
                if len(chapter.get("contents", [])) != original_len:
                    chapter_changed = True

                # Update or append each content block from the snapshot
                for content_row in chapter_data.get("contents", []):
                    row_name = content_row.get("name")
                    if row_name and row_name in existing_map:
                        # Update existing row
                        for existing in chapter.get("contents", []):
                            if existing.name == row_name:
                                if (existing.content_type != content_row.get("content_type", existing.content_type) or
                                    (existing.content_data or "") != (content_row.get("content_data") or "") or
                                    existing.order != content_row.get("order", existing.order) or
                                    (existing.content_reference or "") != (content_row.get("content_reference") or "")):
                                    
                                    existing.content_type = content_row.get("content_type", existing.content_type)
                                    existing.content_data = content_row.get("content_data", "")
                                    existing.order = content_row.get("order", existing.order)
                                    existing.content_reference = content_row.get("content_reference", "")
                                    chapter_changed = True
                                break
                    else:
                        # Append missing row
                        chapter.append("contents", {
                            "content_type": content_row.get("content_type"),
                            "content_data": content_row.get("content_data", ""),
                            "order": content_row.get("order", 0),
                            "content_reference": content_row.get("content_reference", "")
                        })
                        chapter_changed = True

                    # Restore the actual content document (e.g., LMS Text Content)
                    actual_content = content_row.get("actual_content")
                    c_type = content_row.get("content_type")
                    c_ref = content_row.get("content_reference")
                    if actual_content and c_type and c_ref:
                        try:
                            c_doc = frappe.get_doc(c_type, c_ref)
                            c_doc_changed = False
                            for k, v in actual_content.items():
                                if c_doc.meta.has_field(k):
                                    existing_v = getattr(c_doc, k, None)
                                    if existing_v != v and str(existing_v) != str(v):
                                        setattr(c_doc, k, v)
                                        c_doc_changed = True
                            if c_doc_changed:
                                c_doc.flags.ignore_links = True
                                c_doc.save(ignore_permissions=True, ignore_version=True)
                        except frappe.DoesNotExistError:
                            pass
                        except Exception:
                            pass

                if chapter_changed:
                    chapter.flags.ignore_trackers = True
                    chapter.flags.ignore_links = True
                    chapter.save(ignore_permissions=True, ignore_version=True)
            except Exception as e:
                frappe.log_error(f"Failed to restore chapter {chapter_name}: {str(e)}")

    return module_id

    frappe.db.commit()


@frappe.whitelist(allow_guest=False)
def create_module_version(module_id, description=""):
    """
    Creates a new version in the module's version history.
    Takes a full JSON snapshot of all content so it can be restored later.
    """
    module = frappe.get_doc("LMS Module", module_id)
    
    # Reset is_current on all existing versions
    version_history = module.get("version_history", [])
    for v in version_history:
        v.is_current = 0
        
    # Find the true highest version by scanning ALL rows (not just last by index)
    if not version_history:
        new_version = "v1.0"
    else:
        max_major = 1
        max_minor = -1
        for v in version_history:
            try:
                ver_str = str(v.version).lstrip('vV')
                parts = ver_str.split('.')
                if len(parts) == 2:
                    major, minor = int(parts[0]), int(parts[1])
                    if (major, minor) > (max_major, max_minor):
                        max_major, max_minor = major, minor
                else:
                    major = int(float(ver_str))
                    if (major, 0) > (max_major, max_minor):
                        max_major, max_minor = major, 0
            except Exception:
                continue
        
        if max_minor == -1:
            new_version = "v1.0"
        else:
            new_version = f"v{max_major}.{max_minor + 1}"

    # Ensure no duplicate version number (safety check)
    existing_versions = {str(v.version) for v in version_history}
    while new_version in existing_versions:
        try:
            parts = new_version.lstrip('vV').split('.')
            new_version = f"v{parts[0]}.{int(parts[1]) + 1}"
        except Exception:
            new_version = f"v{len(version_history) + 1}.0"
            break

    # Build full content snapshot
    snapshot_json = json.dumps(_build_content_snapshot(module), default=str)

    module.append("version_history", {
        "version": new_version,
        "is_current": 1,
        "description": description,
        "date": today(),
        "author": frappe.session.user
    })
    
    module.save(ignore_permissions=True)

    # Frappe ORM does not reliably persist Long Text fields on child tables
    # through the parent save(). Write the snapshot directly via SQL after save.
    new_row = next(
        (v for v in module.get("version_history", []) if v.version == new_version),
        None
    )
    if new_row:
        frappe.db.set_value(
            "LMS Module Version",
            new_row.name,
            "content_snapshot",
            snapshot_json,
            update_modified=False
        )
        frappe.db.commit()

    return {"message": "success", "new_version": new_version}


@frappe.whitelist(allow_guest=False)
def restore_module_version(module_id, version):
    """
    Restores an older version by applying its saved content snapshot,
    then sets it as is_current=1.
    """
    if not frappe.has_permission("LMS Module", "write", doc=module_id):
        frappe.throw("Not permitted", frappe.PermissionError)

    module = frappe.get_doc("LMS Module", module_id)
    version_history = module.get("version_history", [])
    
    target_v = next((v for v in version_history if v.version == version), None)
    if not target_v:
        frappe.throw(f"Version {version} not found in history.")

    # Apply content snapshot if available
    new_module_id = module_id
    if target_v.content_snapshot:
        try:
            snapshot = json.loads(target_v.content_snapshot)
            new_name = snapshot.get("module_settings", {}).get("module_name")
            new_module_id = _apply_content_snapshot(module_id, snapshot)
        except Exception as e:
            frappe.log_error(f"Failed to restore snapshot for version {version}: {str(e)}")
            frappe.throw(f"Failed to restore content: {str(e)}")

    # Reload module after snapshot apply (save/rename may have happened inside)
    module = frappe.get_doc("LMS Module", new_module_id)
    version_history = module.get("version_history", [])
    target_v = next((v for v in version_history if v.version == version), None)
    
    for v in version_history:
        v.is_current = 1 if (target_v and v.name == target_v.name) else 0
        
    module.save(ignore_permissions=True)
    return {"message": "success", "restored_version": version, "new_id": module.name}


@frappe.whitelist(allow_guest=False)
def has_unpublished_changes(module_id):
    """
    Checks if the module, any of its lessons, any of its chapters,
    or any content blocks inside those chapters have been modified
    since the latest published version.

    Doctypes checked:
      1. LMS Module          - module settings, title, description etc.
      2. LMS Lesson          - lesson title, order, estimated time etc.
      3. LMS Chapter         - chapter title, order etc.
      4. LMS Chapter Content - actual text, video, audio, quiz content blocks

    Uses `creation` (not `modified`) of the version history row as the publish
    baseline, because `modified` gets re-stamped every time the parent module
    is saved, making it unreliable as a change-detection anchor.
    """
    module = frappe.get_doc("LMS Module", module_id)

    versions = module.get("version_history", [])
    if not versions:
        # Never published — always treat as having unpublished changes
        return {"has_changes": True}

    # Use the current version's CREATION time as the publish baseline.
    # `creation` is set once when the row is inserted and never changes.
    latest_v = next((v for v in versions if v.is_current), versions[-1])
    
    
    try:
        if latest_v.content_snapshot:
            old_snapshot = json.loads(latest_v.content_snapshot)
            
            # Ensure certificate and discussion settings don't trigger "unpublished changes"
            if "module_settings" in old_snapshot:
                old_snapshot["module_settings"].pop("enable_certificate", None)
                old_snapshot["module_settings"].pop("enable_discussion", None)
                
            current_snapshot = json.loads(json.dumps(_build_content_snapshot(module), default=str))
            
            if old_snapshot == current_snapshot:
                return {"has_changes": False}
            else:
                return {"has_changes": True}
    except Exception as e:
        frappe.log_error(f"Error comparing snapshots for has_unpublished_changes: {str(e)}")
        return {"has_changes": True}

    return {"has_changes": True}
