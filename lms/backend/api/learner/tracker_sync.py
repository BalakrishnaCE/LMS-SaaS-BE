import frappe
from frappe.model.naming import make_autoname
from frappe.utils import now

def sync_missing_trackers(user):
    if not user or user == "Guest":
        return

    # Mutex lock per user to avoid parallel threads syncing trackers simultaneously
    lock_key = f"sync_missing_trackers_lock_{user}"
    cache = None
    try:
        cache = frappe.cache()
        if cache and cache.get_value(lock_key):
            # Another parallel request is already syncing trackers for this user
            return
        if cache:
            cache.set_value(lock_key, 1, expires_in_sec=5)
    except Exception:
        pass

    try:
        _do_sync_missing_trackers(user)
    except frappe.TimestampMismatchError:
        pass
    except Exception as e:
        frappe.log_error(title=f"Error syncing missing trackers for {user}", message=str(e))
    finally:
        try:
            if cache:
                cache.delete_value(lock_key)
        except Exception:
            pass

def _do_sync_missing_trackers(user):
    from lms.backend.api.common.module_detail import get_all_assigned_modules_for_learner
    from lms.backend.api.learner.dashboard import get_all_assigned_paths_for_learner

    now_time = now()
    commit_needed = False

    # 1. Module Trackers
    assigned_modules = get_all_assigned_modules_for_learner(user)
    if assigned_modules:
        assigned_module_names = list(set([a.get("module") for a in assigned_modules if a.get("module")]))
        if assigned_module_names:
            existing_trackers = frappe.db.sql("""
                SELECT name, module, status, progress_percentage
                FROM `tabLMS Module Tracker`
                WHERE user = %s AND module IN %(modules)s
            """, {"user": user, "modules": tuple(assigned_module_names)}, as_dict=True)
            existing_map = {t.module: t for t in existing_trackers}

            for m in assigned_module_names:
                if m not in existing_map:
                    try:
                        # Double-check existence to prevent race condition duplicates
                        exists = frappe.db.sql("""
                            SELECT name FROM `tabLMS Module Tracker`
                            WHERE user = %s AND module = %s
                            LIMIT 1
                        """, (user, m))
                        if not exists:
                            tracker_name = make_autoname("LMT-.####")
                            frappe.db.sql("""
                                INSERT INTO `tabLMS Module Tracker`
                                (name, user, module, status, progress_percentage, is_saved, creation, modified, modified_by, owner, docstatus)
                                VALUES (%s, %s, %s, 'Not started', 0, 0, %s, %s, %s, %s, 0)
                            """, (tracker_name, user, m, now_time, now_time, user, user))
                            commit_needed = True
                    except Exception:
                        pass
                else:
                    tracker = existing_map[m]
                    if tracker.status == "Unassigned":
                        prog = tracker.progress_percentage or 0
                        restored = "Completed" if prog >= 100 else ("In Progress" if prog > 0 else "Not started")
                        frappe.db.sql("""
                            UPDATE `tabLMS Module Tracker`
                            SET status = %s, modified = %s, modified_by = %s
                            WHERE name = %s
                        """, (restored, now_time, user, tracker.name))
                        commit_needed = True

    # 2. Learning Path Trackers
    assigned_paths = get_all_assigned_paths_for_learner(user)
    if assigned_paths:
        assigned_path_names = list(set([a.get("learning_path") for a in assigned_paths if a.get("learning_path")]))
        if assigned_path_names:
            existing_lp_trackers = frappe.db.sql("""
                SELECT name, learning_path, status, progress_percentage
                FROM `tabLMS Learning Path Tracker`
                WHERE user = %s AND learning_path IN %(paths)s
            """, {"user": user, "paths": tuple(assigned_path_names)}, as_dict=True)
            existing_lp_map = {t.learning_path: t for t in existing_lp_trackers}

            for p in assigned_path_names:
                if p not in existing_lp_map:
                    try:
                        # Double-check existence to prevent race condition duplicates
                        exists = frappe.db.sql("""
                            SELECT name FROM `tabLMS Learning Path Tracker`
                            WHERE user = %s AND learning_path = %s
                            LIMIT 1
                        """, (user, p))
                        if not exists:
                            tracker_name = make_autoname("LLPT-.####")
                            frappe.db.sql("""
                                INSERT INTO `tabLMS Learning Path Tracker`
                                (name, user, learning_path, status, progress_percentage, is_saved, creation, modified, modified_by, owner, docstatus)
                                VALUES (%s, %s, %s, 'Not started', 0, 0, %s, %s, %s, %s, 0)
                            """, (tracker_name, user, p, now_time, now_time, user, user))
                            commit_needed = True
                    except Exception:
                        pass
                else:
                    tracker = existing_lp_map[p]
                    if tracker.status == "Unassigned":
                        prog = tracker.progress_percentage or 0
                        restored = "Completed" if prog >= 100 else ("In Progress" if prog > 0 else "Not started")
                        frappe.db.sql("""
                            UPDATE `tabLMS Learning Path Tracker`
                            SET status = %s, modified = %s, modified_by = %s
                            WHERE name = %s
                        """, (restored, now_time, user, tracker.name))
                        commit_needed = True

    if commit_needed:
        frappe.db.commit()
