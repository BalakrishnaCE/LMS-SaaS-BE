import frappe

def sync_missing_trackers(user):
    from lms.backend.api.common.module_detail import get_all_assigned_modules_for_learner
    from lms.backend.api.learner.dashboard import get_all_assigned_paths_for_learner
    
    commit_needed = False
    
    assigned_modules = get_all_assigned_modules_for_learner(user)
    if assigned_modules:
        assigned_module_names = list(set([a.get("module") for a in assigned_modules if a.get("module")]))
        if assigned_module_names:
            existing_trackers = frappe.get_all(
                "LMS Module Tracker",
                filters={"user": user, "module": ("in", assigned_module_names)},
                fields=["name", "module", "status", "progress_percentage"]
            )
            existing_map = {t.module: t for t in existing_trackers}
            
            for m in assigned_module_names:
                if m not in existing_map:
                    doc = frappe.new_doc("LMS Module Tracker")
                    doc.user = user
                    doc.module = m
                    doc.status = "Not started"
                    doc.progress_percentage = 0
                    doc.insert(ignore_permissions=True)
                    commit_needed = True
                else:
                    tracker = existing_map[m]
                    if tracker.status == "Unassigned":
                        prog = tracker.progress_percentage or 0
                        restored = "Completed" if prog >= 100 else ("In Progress" if prog > 0 else "Not started")
                        frappe.db.set_value("LMS Module Tracker", tracker.name, "status", restored)
                        commit_needed = True

    assigned_paths = get_all_assigned_paths_for_learner(user)
    if assigned_paths:
        assigned_path_names = list(set([a.get("learning_path") for a in assigned_paths if a.get("learning_path")]))
        if assigned_path_names:
            existing_trackers = frappe.get_all(
                "LMS Learning Path Tracker",
                filters={"user": user, "learning_path": ("in", assigned_path_names)},
                fields=["name", "learning_path", "status", "progress_percentage"]
            )
            existing_map = {t.learning_path: t for t in existing_trackers}
            
            for p in assigned_path_names:
                if p not in existing_map:
                    doc = frappe.new_doc("LMS Learning Path Tracker")
                    doc.user = user
                    doc.learning_path = p
                    doc.status = "Not started"
                    doc.progress_percentage = 0
                    doc.insert(ignore_permissions=True)
                    commit_needed = True
                else:
                    tracker = existing_map[p]
                    if tracker.status == "Unassigned":
                        prog = tracker.progress_percentage or 0
                        restored = "Completed" if prog >= 100 else ("In Progress" if prog > 0 else "Not started")
                        frappe.db.set_value("LMS Learning Path Tracker", tracker.name, "status", restored)
                        commit_needed = True
                
    if commit_needed:
        frappe.db.commit()
