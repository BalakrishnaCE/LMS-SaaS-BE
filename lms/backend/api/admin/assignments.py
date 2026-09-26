import frappe
from frappe.utils import getdate

@frappe.whitelist()
def get_admin_assignments():
    # Check permissions
    if not frappe.has_permission("LMS Module Assignment", "read"):
        frappe.throw("Not permitted", frappe.PermissionError)
        
    modules = frappe.get_all(
        "LMS Module Assignment",
        fields=["name", "module", "assignment_type", "is_mandatory", "duration", "creation", "team", "assignee_type"],
        order_by="creation desc",
        limit_page_length=500
    )
    
    paths = frappe.get_all(
        "LMS Learning Path Assignment",
        fields=["name", "learning_path", "assignment_type", "is_mandatory", "duration", "creation"],
        order_by="creation desc",
        limit_page_length=500,
        ignore_permissions=True
    )
    
    # Get all manual assignment users
    mod_users = frappe.get_all(
        "LMS Assignment User",
        filters={"parenttype": "LMS Module Assignment"},
        fields=["parent", "user"]
    )
    path_users = frappe.get_all(
        "LMS Assignment User",
        filters={"parenttype": "LMS Learning Path Assignment"},
        fields=["parent", "user"]
    )
    
    # Group users by parent
    mod_user_map = {}
    for u in mod_users:
        mod_user_map.setdefault(u.parent, []).append(u.user)
        
    path_user_map = {}
    for u in path_users:
        path_user_map.setdefault(u.parent, []).append(u.user)
        
    # Get enrollments to determine progress
    # We will fetch all enrollments and index by (module/path, user)
    mod_enrollments = frappe.get_all(
        "LMS Module Tracker",
        filters={"status": ["!=", "Unassigned"]},
        fields=["name", "module", "user", "status", "progress_percentage", "creation", "assignment"]
    )
    mod_enroll_map = {}
    for e in mod_enrollments:
        mod_enroll_map[(e.module, e.user)] = e
        
    path_enrollments = frappe.get_all(
        "LMS Learning Path Tracker",
        filters={"status": ["!=", "Unassigned"]},
        fields=["name", "learning_path", "user", "status", "progress_percentage", "creation"]
    )
    path_enroll_map = {}
    for e in path_enrollments:
        path_enroll_map[(e.learning_path, e.user)] = e

    return {
        "modules": modules,
        "paths": paths,
        "mod_users": mod_user_map,
        "path_users": path_user_map,
        "mod_enrollments": mod_enrollments, # Just return raw for frontend to map if needed
        "path_enrollments": path_enrollments
    }

@frappe.whitelist()
def toggle_assignment_status(tracker_type, tracker_name, status):
    if not frappe.has_permission(tracker_type, "write"):
        frappe.throw("Not permitted", frappe.PermissionError)
    
    frappe.db.set_value(tracker_type, tracker_name, "status", status)
    return True

@frappe.whitelist()
def check_assignment_overlap():
    import json
    if not frappe.has_permission("LMS Module Assignment", "read"):
        frappe.throw("Not permitted", frappe.PermissionError)
    
    # frappeCall sends POST with Content-Type: application/json
    # so data arrives in the JSON body, not form_dict
    try:
        body = frappe.request.get_json(force=True) or {}
    except Exception:
        body = {}
    
    # Support both: payload as a nested JSON string (legacy) or direct keys
    payload_str = body.get('payload') or frappe.form_dict.get('payload')
    if payload_str:
        try:
            payload = json.loads(payload_str) if isinstance(payload_str, str) else payload_str
        except Exception:
            payload = {}
    else:
        payload = body

    modules = payload.get('modules', [])
    paths = payload.get('paths', [])
    everyone = payload.get('everyone', False)
    teams = payload.get('teams', [])
    learners = payload.get('learners', [])
    
    users = set()
    
    if everyone:
        lms_roles = frappe.get_all("Has Role", filters={"role": ["in", ["LMS-Learner", "LMS-TL"]]}, fields=["parent"])
        valid_users = [r.parent for r in lms_roles if r.parent not in ["Administrator", "Guest"]]
        all_users = frappe.get_all(
            "User",
            filters={"enabled": 1, "name": ["in", valid_users] if valid_users else ["in", ["__nobody__"]]},
            fields=["name"]
        )
        users.update([u.name for u in all_users])
    else:
        for t in teams:
            members = frappe.get_all("LMS Team Member", filters={"parent": t}, fields=["user"])
            users.update([m.user for m in members if m.user])
        users.update(learners)
        
    if not users:
        return {"overlap_count": 0, "department_summary": ""}
        
    overlapping_users = set()
    
    if modules:
        trackers = frappe.get_all("LMS Module Tracker", 
            filters={"module": ["in", modules], "user": ["in", list(users)], "status": ["!=", "Unassigned"]},
            fields=["user"]
        )
        overlapping_users.update([t.user for t in trackers])
        
    if paths:
        trackers = frappe.get_all("LMS Learning Path Tracker", 
            filters={"learning_path": ["in", paths], "user": ["in", list(users)], "status": ["!=", "Unassigned"]},
            fields=["user"]
        )
        overlapping_users.update([t.user for t in trackers])
        
    if not overlapping_users:
        return {"overlap_count": 0, "department_summary": ""}
        
    # Group overlapping users by department to generate summary like "8 Sales · 4 Marketing"
    dept_counts = {}
    
    # Get all users' departments via LMS Team Member
    team_members = frappe.get_all("LMS Team Member", filters={"user": ["in", list(overlapping_users)]}, fields=["user", "parent"])
    
    user_teams = {}
    for tm in team_members:
        user_teams.setdefault(tm.user, []).append(tm.parent)
        
    no_team_count = 0
    for u in overlapping_users:
        user_depts = user_teams.get(u, [])
        if not user_depts:
            no_team_count += 1
        else:
            # Just count them in their first department for simplicity in the summary
            dept_counts[user_depts[0]] = dept_counts.get(user_depts[0], 0) + 1
            
    summary_parts = []
    # Get team names
    if dept_counts:
        teams_info = frappe.get_all("LMS Team", filters={"name": ["in", list(dept_counts.keys())]}, fields=["name", "team_name"])
        team_name_map = {t.name: t.team_name for t in teams_info}
        
        for dept, count in dept_counts.items():
            name = team_name_map.get(dept, dept)
            summary_parts.append(f"{count} {name}")
            
    if no_team_count > 0:
        summary_parts.append(f"{no_team_count} Individuals")
        
    summary = " · ".join(summary_parts)
    
    # Fetch user details
    detailed_users = []
    if overlapping_users:
        user_records = frappe.get_all("User", filters={"name": ["in", list(overlapping_users)]}, fields=["name", "full_name"])
        user_map = {u.name: u for u in user_records}
        
        for u in overlapping_users:
            user_doc = user_map.get(u, {})
            u_depts = user_teams.get(u, [])
            dept_name = team_name_map.get(u_depts[0], u_depts[0]) if u_depts else "Individual"
            
            detailed_users.append({
                "email": u,
                "full_name": user_doc.get("full_name") or u.split("@")[0],
                "department": dept_name,
                "role": "Learner" # Defaulting to Learner
            })
    
    return {
        "overlap_count": len(overlapping_users),
        "department_summary": summary,
        "overlapping_users": detailed_users
    }
