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
    if tracker_name:
        tracker_doc = frappe.get_doc("LMS Learning Path Tracker", tracker_name)
        
    # Get Module Trackers directly as the source of truth
    module_names = [pc.module for pc in path_courses]
    module_progress_map = {}
    if module_names:
        module_trackers = frappe.get_all(
            "LMS Module Tracker",
            filters={"user": user, "module": ["in", module_names]},
            fields=["module", "status", "progress_percentage"]
        )
        for mt in module_trackers:
            module_progress_map[mt.module] = {
                "status": mt.status,
                "score": mt.progress_percentage
            }

    modules = []
    completed_modules = 0
    total_duration = 0
    total_progress = 0
    
    # We also want to know how many assessments/quizzes are inside these modules to display "Path Includes"
    total_quizzes = 0
    total_assessments = 0

    from lms.backend.api.common.module_detail import get_module_duration_mins, format_duration_str
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
            
            if mod_prog.get("status") == "Unassigned":
                continue
                
            mod["learner_status"] = mod_prog.get("status", "Not Started")
            mod["learner_score"] = mod_prog.get("score", 0)
            
            if mod["learner_status"] == "Completed":
                completed_modules += 1
                
            total_progress += mod["learner_score"]
                
            # Accumulate overall duration using actual module curriculum duration
            curriculum_mins = get_module_duration_mins(mod.name)
            mod["duration"] = curriculum_mins
            mod["duration_str"] = format_duration_str(curriculum_mins)
            total_duration += curriculum_mins
            
            modules.append(mod)

    # Count quizzes and QA assessments across all modules in this learning path
    total_quizzes = 0
    total_qa_assessments = 0
    valid_module_names = [m["name"] for m in modules]

    if valid_module_names:
        # 1. Fetch chapter contents for these modules
        chapter_contents = frappe.db.sql("""
            SELECT cc.content_type, cc.content_reference
            FROM `tabLMS Module Lesson Child` mlc
            JOIN `tabLMS Lesson Chapter` lc ON lc.parent = mlc.lesson
            JOIN `tabLMS Chapter Content` cc ON cc.parent = lc.chapter
            WHERE mlc.parent IN %(modules)s 
              AND cc.content_type IN ('LMS Quiz Content', 'LMS Assessment Content')
        """, {"modules": valid_module_names}, as_dict=True)

        for item in chapter_contents:
            quiz_id = None
            if item.content_type == "LMS Quiz Content":
                quiz_id = frappe.db.get_value("LMS Quiz Content", item.content_reference, "quiz")
            elif item.content_type == "LMS Assessment Content":
                quiz_id = frappe.db.get_value("LMS Assessment Content", item.content_reference, "assessment")

            if quiz_id:
                q_type = frappe.db.get_value("LMS Quiz", quiz_id, "quiz_type")
                if q_type == "QA Assessment":
                    total_qa_assessments += 1
                else:
                    total_quizzes += 1
            else:
                if item.content_type == "LMS Assessment Content":
                    total_qa_assessments += 1
                else:
                    total_quizzes += 1

        # 2. Module level assessments (tabLMS Module Assessment)
        mod_assessments = frappe.get_all(
            "LMS Module Assessment",
            filters={"parent": ["in", valid_module_names]},
            fields=["assessment"]
        )
        for ma in mod_assessments:
            q_type = frappe.db.get_value("LMS Quiz", ma.assessment, "quiz_type")
            if q_type == "QA Assessment":
                total_qa_assessments += 1
            else:
                total_quizzes += 1

    # Format Duration
    duration_str = format_duration_str(total_duration)

    # Overall progress percentage
    progress_percentage = 0
    if len(modules) > 0:
        progress_percentage = round((total_progress / len(modules)), 2)
        
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
        "isSaved": bool(tracker_doc.is_saved) if tracker_doc else False,
        "duration_str": duration_str.strip(),
        "total_duration": total_duration,
        "includes": {
            "modules": len(modules),
            "quizzes": total_quizzes,
            "assessments": total_qa_assessments,
            "total_assessments": total_quizzes + total_qa_assessments,
            "certificates": 1 if path.enable_certificate else 0
        }
    }

@frappe.whitelist()
def get_learner_paths():
    """
    Returns all published Learning Paths for the Learner along with their progress.
    """
    user = frappe.session.user
    
    from lms.backend.api.learner.tracker_sync import sync_missing_trackers
    sync_missing_trackers(user)

    # Get only learning paths this user has been assigned/enrolled in
    user_lp_trackers = frappe.get_all(
        "LMS Learning Path Tracker",
        filters={"user": user},
        fields=["learning_path", "status", "progress_percentage", "is_saved"]
    )
    assigned_lp_names = [t.learning_path for t in user_lp_trackers]
    lp_tracker_map = {t.learning_path: t for t in user_lp_trackers}

    if not assigned_lp_names:
        return {"paths": []}

    # Get only the assigned paths that are published
    paths = frappe.get_all(
        "LMS Learning Path",
        filters={"name": ["in", assigned_lp_names], "status": "Published"},
        fields=["name", "path_name", "description", "image", "is_mandatory"]
    )

    # Get user's module trackers
    module_trackers = frappe.get_all(
        "LMS Module Tracker",
        filters={"user": user},
        fields=["module", "status", "progress_percentage"]
    )
    module_status_map = {mt.module: mt for mt in module_trackers}

    for path in paths:
        # Get category from child table
        categories = frappe.get_all(
            "LMS Module Category",
            filters={"parent": path.name, "parenttype": "LMS Learning Path"},
            fields=["category"]
        )
        cat_list = [c.category for c in categories if c.category]
        path.categories = cat_list
        path.category = cat_list if cat_list else "General"

        # Get modules for this path (include duration for time estimation)
        modules = frappe.get_all("LMS Learning Path Course", filters={"parent": path.name}, fields=["module"])
        
        completed_modules = 0
        total_progress = 0
        valid_module_count = 0
        total_duration_minutes = 0
        
        for m in modules:
            mt = module_status_map.get(m.module)
            if mt and mt.status == "Unassigned":
                continue
                
            valid_module_count += 1
            from lms.backend.api.common.module_detail import get_module_duration_mins
            mod_duration = get_module_duration_mins(m.module)
            total_duration_minutes += int(mod_duration)

            if mt:
                if mt.status == "Completed":
                    completed_modules += 1
                if mt.progress_percentage:
                    total_progress += mt.progress_percentage
        
        path.module_count = valid_module_count
        path.total_duration_minutes = total_duration_minutes
        
        if valid_module_count > 0:
            path.progress_percentage = round((total_progress / valid_module_count), 2)
        else:
            path.progress_percentage = 0
            
        if path.progress_percentage == 100:
            path.learner_status = "Completed"
        elif path.progress_percentage > 0:
            path.learner_status = "In Progress"
        else:
            path.learner_status = "Not Started"
            
        # Get is_saved from the tracker
        tracker = lp_tracker_map.get(path.name)
        path.isSaved = bool(tracker.is_saved) if tracker else False
            
        path.id = path.name

    return {
        "paths": paths
    }
