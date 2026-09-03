import frappe
from frappe import _

@frappe.whitelist()
def get_learner_path_detail(path_id):
    """
    Returns the full detail of a single Learning Path tailored for a specific Learner.
    Includes metadata, categories, modules, and the user's specific progress via LMS Learning Path Tracker.
    """
    user = frappe.session.user

    # Verify path exists
    if not frappe.db.exists("LMS Learning Path", path_id):
        frappe.throw(_("Learning Path not found"), frappe.DoesNotExistError)

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

    # Fetch Learner's Tracker if it exists
    tracker_name = frappe.db.get_value(
        "LMS Learning Path Tracker",
        {"user": user, "learning_path": path_id},
        "name"
    )
    
    tracker_doc = None
    module_progress_map = {}
    if tracker_name:
        tracker_doc = frappe.get_doc("LMS Learning Path Tracker", tracker_name)
        for progress in tracker_doc.get("module_progress", []):
            module_progress_map[progress.module] = {
                "status": progress.status,
                "score": progress.score
            }

    modules = []
    completed_modules = 0
    total_duration = 0
    
    # We also want to know how many assessments/quizzes are inside these modules to display "Path Includes"
    total_quizzes = 0
    total_assessments = 0

    for pc in path_courses:
        mod = frappe.get_value(
            "LMS Module",
            pc.module,
            ["name", "module_name", "description", "image", "duration"],
            as_dict=True
        )
        if mod:
            # Count lessons
            lesson_count_res = frappe.db.sql("""
                SELECT count(name)
                FROM `tabLMS Module Lesson Child`
                WHERE parent = %s AND parenttype = 'LMS Module'
            """, (mod.name,))
            mod["lesson_count"] = lesson_count_res[0][0] if lesson_count_res else 0
            
            # Identify progress for this module from the tracker map
            mod_prog = module_progress_map.get(mod.name, {})
            mod["learner_status"] = mod_prog.get("status", "Not Started")
            mod["learner_score"] = mod_prog.get("score", 0)
            
            if mod["learner_status"] == "Completed":
                completed_modules += 1
                
            # Accumulate overall duration
            mod_duration = mod.get("duration") or 0
            total_duration += mod_duration
            
            # Optional: count quizzes/assessments
            # Assuming QA Assessments are interactive elements or similar, we'll keep it simple for now
            total_quizzes += 0

            modules.append(mod)

    # Format Duration
    hours = total_duration // 60
    mins = total_duration % 60
    duration_str = ""
    if hours > 0:
        duration_str += f"{hours} hrs "
    if mins > 0 or hours == 0:
        duration_str += f"{mins} min"

    # Overall progress percentage
    progress_percentage = 0
    if len(modules) > 0:
        progress_percentage = (completed_modules / len(modules)) * 100
        
    if tracker_doc and tracker_doc.progress_percentage is not None:
        progress_percentage = tracker_doc.progress_percentage

    return {
        "id": path.name,
        "title": path.path_name,
        "description": path.description,
        "image": path.image,
        "status": path.status,
        "is_mandatory": path.is_mandatory,
        "is_sequential": path.is_sequential,
        "modified": str(path.modified),
        "categories": category_list,
        "category": category_list[0] if category_list else "General",
        "modules": modules,
        "total_modules": len(modules),
        "completed_modules": completed_modules,
        "progress_percentage": progress_percentage,
        "duration_str": duration_str.strip(),
        "total_duration": total_duration,
        "includes": {
            "modules": len(modules),
            "quizzes": total_quizzes,
            "assessments": 0,
            "certificates": 1 # Assume 1 certificate for now
        }
    }
