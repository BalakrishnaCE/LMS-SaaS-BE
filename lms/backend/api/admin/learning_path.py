import frappe
from frappe import _

@frappe.whitelist()
def get_learning_paths():
    """
    Returns aggregated statistics and a list of all Learning Paths.
    """
    paths = frappe.get_all(
        "LMS Learning Path",
        fields=["name", "path_name", "status", "description", "image", "is_sequential", "modified", "is_mandatory"],
        order_by="modified desc"
    )

    # Get modules for each path
    for path in paths:
        courses = frappe.get_all(
            "LMS Learning Path Course",
            filters={"parent": path.name},
            fields=["module", "sequence_order"],
            order_by="sequence_order asc"
        )
        path["modules"] = courses
        path["module_count"] = len(courses)
        
        # Get category
        categories = frappe.get_all(
            "LMS Module Category",
            filters={"parent": path.name, "parenttype": "LMS Learning Path"},
            fields=["category"]
        )
        if categories:
            path["category"] = categories[0].category
        else:
            path["category"] = ""
        
        # Calculate completion rate
        enrollments = frappe.get_all(
            "LMS Learning Path Enrollment",
            filters={"learning_path": path.name},
            fields=["status", "completion_percentage"]
        )
        completed = sum(1 for e in enrollments if e.status == "Completed")
        path["enrollment_count"] = len(enrollments)
        path["completed_count"] = completed

    # Calculate Header Stats
    total_paths = len(paths)
    draft_paths = sum(1 for p in paths if p.status == "Draft")
    
    overdue_learners = 0 
    review_required = 0

    return {
        "stats": {
            "total_paths": total_paths,
            "overdue_learners": overdue_learners,
            "draft_paths": draft_paths,
            "review_required": review_required
        },
        "paths": paths
    }

@frappe.whitelist()
def get_learning_path_detail(path_id):
    """
    Returns the full detail of a single Learning Path for the details view.
    Includes metadata, categories, and all assigned modules with their details.
    """
    path = frappe.get_doc("LMS Learning Path", path_id)

    # Categories
    categories = frappe.get_all(
        "LMS Module Category",
        filters={"parent": path_id, "parenttype": "LMS Learning Path"},
        fields=["category"]
    )
    category_list = [c.category for c in categories]

    # Modules in order
    path_courses = frappe.get_all(
        "LMS Learning Path Course",
        filters={"parent": path_id},
        fields=["module", "sequence_order"],
        order_by="sequence_order asc"
    )

    modules = []
    for pc in path_courses:
        mod = frappe.get_value(
            "LMS Module",
            pc.module,
            ["name", "module_name", "description", "image", "duration"],
            as_dict=True
        )
        if mod:
            # Count lessons using the same pattern as module_management.py
            lesson_count_res = frappe.db.sql("""
                SELECT count(name)
                FROM `tabLMS Module Lesson Child`
                WHERE parent = %s AND parenttype = 'LMS Module'
            """, (mod.name,))
            mod["lesson_count"] = lesson_count_res[0][0] if lesson_count_res else 0
            modules.append(mod)

    total_duration = sum(m.get("duration") or 0 for m in modules)
    hours = total_duration // 60
    mins = total_duration % 60
    duration_str = ""
    if hours > 0:
        duration_str += f"{hours} hrs "
    if mins > 0 or hours == 0:
        duration_str += f"{mins} min"

    return {
        "name": path.name,
        "path_name": path.path_name,
        "description": path.description,
        "image": path.image,
        "status": path.status,
        "is_mandatory": path.is_mandatory,
        "is_sequential": path.is_sequential,
        "modified": str(path.modified),
        "categories": category_list,
        "category": category_list[0] if category_list else "",
        "modules": modules,
        "module_count": len(modules),
        "duration_str": duration_str.strip(),
        "total_duration": total_duration,
    }

@frappe.whitelist(allow_guest=False)
def duplicate_learning_path(path_name):
    if not path_name:
        frappe.throw("Path Name is required")
        
    original = frappe.get_doc("LMS Learning Path", path_name)
    
    # Generate unique name
    base_name = f"{original.path_name} (Copy)"
    new_name = base_name
    counter = 1
    
    # Check if a path with this path_name already exists (not the doc name, but the field path_name)
    while frappe.db.exists("LMS Learning Path", {"path_name": new_name}):
        new_name = f"{base_name} {counter}"
        counter += 1
        
    # Create copy
    new_path = frappe.copy_doc(original)
    
    new_path.path_name = new_name
    new_path.status = "Draft"
    new_path.insert(ignore_permissions=True)
    
    return {"status": "success", "new_path_id": new_path.name}
