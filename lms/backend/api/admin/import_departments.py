import frappe
import json

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
            team_doc.insert(ignore_permissions=True)
            team_name = team_doc.name
            
        # Update managers (Team Leads)
        existing_managers = {row.user for row in team_doc.get("team_leads", [])}
        for email in valid_managers:
            if email not in existing_managers:
                team_doc.append("team_leads", {"user": email})
        
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
