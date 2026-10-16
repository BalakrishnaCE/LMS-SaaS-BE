import frappe
import json
from frappe.utils import getdate

def _validate_manager(email):
    """
    Check if a user exists with the given email.
    """
    if not email:
        return False
    return frappe.db.exists("User", email.strip())

@frappe.whitelist()
def save_department_import(departments_json, groups_json="[]"):
    """
    Saves imported departments and assigns learning to them.
    departments_json: list of dicts [{"department_name": "Sales", "managers": "mgr1@example.com, mgr2@example.com"}]
    groups_json: JSON string of assignment groups containing the departments and selectedContent
    """
    departments = json.loads(departments_json) if isinstance(departments_json, str) else departments_json
    groups = json.loads(groups_json) if isinstance(groups_json, str) else groups_json

    created_teams = {} # Map original department name to LMS Team ID

    # 1. Parse and create departments
    for dep in departments:
        dept_name = dep.get("department_name", "").strip()
        if not dept_name:
            continue
        
        managers_raw = dep.get("managers", "")
        manager_emails = [m.strip() for m in managers_raw.split(",")] if managers_raw else []
        valid_managers = [email for email in manager_emails if _validate_manager(email)]

        # Find or create Team
        team_name = frappe.db.get_value("LMS Team", {"team_name": dept_name}, "name")
        if team_name:
            team_doc = frappe.get_doc("LMS Team", team_name)
        else:
            team_doc = frappe.new_doc("LMS Team")
            team_doc.team_name = dept_name
            team_doc.is_active = 1
            
        # Update managers (Team Leads)
        existing_managers = {row.user for row in (team_doc.get("team_leads") or [])}
        for email in valid_managers:
            if email not in existing_managers:
                team_doc.append("team_leads", {"user": email})
                
        # Update learners (Team Members)
        existing_members = {row.user for row in (team_doc.get("learners") or [])}
        learners = dep.get("learners", [])
        for l in learners:
            l_email = l.get("email", "").strip()
            if not l_email: continue
            
            # Create user if doesn't exist
            if not frappe.db.exists("User", l_email):
                new_user = frappe.new_doc("User")
                new_user.email = l_email
                new_user.first_name = l.get("name", l_email.split("@")[0])
                
                base_username = l_email.split("@")[0]
                username = base_username
                if frappe.db.exists("User", {"username": username}):
                    import uuid
                    username = f"{base_username}_{uuid.uuid4().hex[:6]}"
                new_user.username = username
                
                new_user.send_welcome_email = 0
                new_user.append("roles", {"role": "LMS-Learner"})
                new_user.append("roles", {"role": "System Manager"})
                new_user.insert(ignore_permissions=True)
            
            if l_email not in existing_members:
                team_doc.append("learners", {
                    "user": l_email
                })
                
            # Update or create LMS User Settings
            user_settings_name = frappe.db.get_value("LMS User Settings", {"system_user": l_email}, "name")
            if user_settings_name:
                settings_doc = frappe.get_doc("LMS User Settings", user_settings_name)
            else:
                settings_doc = frappe.new_doc("LMS User Settings")
                settings_doc.system_user = l_email
                
            has_changes = False
            designation = l.get("designation", "").strip()
            joined_date_raw = l.get("joined_date", "") if l.get("joined_date") else None
            
            parsed_date = None
            if joined_date_raw:
                try:
                    from dateutil.parser import parse as parse_date
                    parsed_date = parse_date(joined_date_raw, dayfirst=True).strftime("%Y-%m-%d")
                except Exception:
                    pass
            
            if designation and settings_doc.designation != designation:
                settings_doc.designation = designation
                has_changes = True
                
            if parsed_date and str(settings_doc.joining_date) != str(parsed_date):
                settings_doc.joining_date = parsed_date
                has_changes = True
                
            if settings_doc.is_new():
                settings_doc.insert(ignore_permissions=True)
            elif has_changes:
                settings_doc.save(ignore_permissions=True)
        
        if team_doc.is_new():
            team_doc.insert(ignore_permissions=True)
            team_name = team_doc.name
        else:
            team_doc.save(ignore_permissions=True)
            
        created_teams[dept_name] = team_name
        
    # 2. Process assignment groups for content assignment
    for group in groups:
        assigned_departments = group.get("departments", [])
        selected_content = group.get("selectedContent", [])
        
        if not assigned_departments or not selected_content:
            continue
            
        team_ids = []
        for dep in assigned_departments:
            original_name = dep.get("department_name", "").strip()
            if original_name in created_teams:
                team_ids.append(created_teams[original_name])
                
        if not team_ids:
            continue
            
        modules = [c for c in selected_content if c.get("type") == "module"]
        learning_paths = [c for c in selected_content if c.get("type") == "learning_path"]
        
        # Assign Modules to Teams
        for mod in modules:
            mod_id = mod.get("id")
            if not mod_id:
                continue
            
            existing = frappe.db.get_value(
                "LMS Module Assignment",
                {"module": mod_id, "assignment_type": "Team"},
                "name"
            )
            
            if existing:
                doc = frappe.get_doc("LMS Module Assignment", existing)
                existing_teams = {row.team for row in doc.get("assigned_teams", [])}
                for t_id in team_ids:
                    if t_id not in existing_teams:
                        doc.append("assigned_teams", {"team": t_id})
                doc.save(ignore_permissions=True)
            else:
                doc = frappe.new_doc("LMS Module Assignment")
                doc.module = mod_id
                doc.assignment_type = "Team"
                for t_id in team_ids:
                    doc.append("assigned_teams", {"team": t_id})
                doc.insert(ignore_permissions=True)
                
        # Assign Learning Paths to Teams
        for lp in learning_paths:
            lp_id = lp.get("id")
            if not lp_id:
                continue
                
            existing = frappe.db.get_value(
                "LMS Learning Path Assignment",
                {"learning_path": lp_id, "assignment_type": "Team"},
                "name"
            )
            
            if existing:
                doc = frappe.get_doc("LMS Learning Path Assignment", existing)
                existing_teams = {row.team for row in doc.get("assigned_teams", [])}
                for t_id in team_ids:
                    if t_id not in existing_teams:
                        doc.append("assigned_teams", {"team": t_id})
                doc.save(ignore_permissions=True)
            else:
                doc = frappe.new_doc("LMS Learning Path Assignment")
                doc.learning_path = lp_id
                doc.assignment_type = "Team"
                for t_id in team_ids:
                    doc.append("assigned_teams", {"team": t_id})
                doc.insert(ignore_permissions=True)
                
    frappe.db.commit()
    return {"status": "success", "departments_created": len(created_teams)}
