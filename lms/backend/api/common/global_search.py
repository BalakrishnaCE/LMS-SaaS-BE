import frappe

@frappe.whitelist()
def search(query=""):
    if not query:
        return {"modules": [], "learning_paths": [], "learners": []}
        
    user = frappe.session.user
    roles = frappe.get_roles(user)
    is_admin = "LMS-Admin" in roles or "System Manager" in roles
    is_manager = "LMS-TL" in roles

    module_filters = [["module_name", "like", f"%{query}%"]]
    path_filters = [["path_name", "like", f"%{query}%"]]
    learner_filters = [["full_name", "like", f"%{query}%"], ["enabled", "=", 1], ["name", "!=", "Administrator"]]

    if not is_admin:
        module_filters.append(["status", "=", "Published"])
        path_filters.append(["status", "=", "Published"])
        
        assigned_modules = [t.module for t in frappe.get_all("LMS Module Tracker", filters={"user": user}, fields=["module"])]
        if assigned_modules:
            module_filters.append(["name", "in", assigned_modules])
        else:
            module_filters.append(["name", "=", "___NONE___"])
            
        assigned_paths = [t.learning_path for t in frappe.get_all("LMS Learning Path Tracker", filters={"user": user}, fields=["learning_path"])]
        if assigned_paths:
            path_filters.append(["name", "in", assigned_paths])
        else:
            path_filters.append(["name", "=", "___NONE___"])

        if is_manager:
            from lms.backend.api.manager.metrics import _get_team_member_emails
            team_members = _get_team_member_emails(user)
            if team_members:
                learner_filters.append(["name", "in", team_members])
            else:
                learner_filters.append(["name", "=", "___NONE___"])
        else:
            # Learners shouldn't see other learners anyway
            learner_filters.append(["name", "=", "___NONE___"])

    modules_raw = frappe.get_all(
        "LMS Module", 
        filters=module_filters, 
        fields=["name", "module_name as title", "image"], 
        limit=10
    )
    
    paths_raw = frappe.get_all(
        "LMS Learning Path", 
        filters=path_filters, 
        fields=["name", "path_name as title", "image"], 
        limit=10
    )
    
    learners = frappe.get_all(
        "User", 
        filters=learner_filters, 
        fields=["name as email", "full_name", "user_image"], 
        limit=10
    )
    
    # Sort to prioritize exact matches and prefix matches
    lower_q = query.lower()
    def sort_key(item, field="title"):
        val = (item.get(field) or "").lower()
        if val == lower_q: return 0
        if val.startswith(lower_q): return 1
        # if any word in the string starts with the query (e.g. "John Doe" for "Do")
        if f" {lower_q}" in val: return 2
        return 3

    modules_raw.sort(key=lambda x: sort_key(x, "title"))
    paths_raw.sort(key=lambda x: sort_key(x, "title"))
    learners.sort(key=lambda x: sort_key(x, "full_name"))
    
    return {
        "modules": modules_raw[:5],
        "learning_paths": paths_raw[:5],
        "learners": learners[:5]
    }
