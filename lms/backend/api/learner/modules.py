import frappe
from frappe.utils import today, add_days, getdate, date_diff
from lms.backend.api.common.module_detail import get_estimated_hours_from_curriculum
from lms.backend.api.learner.dashboard import get_module_category

@frappe.whitelist()
def check_module_has_attempts_left(user, module_name):
    from lms.backend.api.admin.module_management import get_curriculum
    curriculum = get_curriculum(module_name)
    quiz_names = []
    for lesson in curriculum:
        for chapter in lesson.get("chapters", []):
            for content in chapter.get("contents", []):
                if content.get("contentType") in ["quiz", "assessment"]:
                    q_data = content.get("contentData", {})
                    if q_data and "quiz_data" in q_data:
                        q_info = q_data.get("quiz_data")
                        if q_info and q_info.get("name") and q_info.get("is_passing_required"):
                            quiz_names.append(q_info["name"])
    
    for q_name in quiz_names:
        max_att = frappe.db.get_value("LMS Quiz", q_name, "max_attempts") or 0
        if max_att > 0:
            subs = frappe.get_all("LMS Quiz Submission", filters={"user": user, "quiz": q_name}, fields=["extra_attempts_granted"])
            att_used = len(subs)
            extra_attempts = sum([s.extra_attempts_granted or 0 for s in subs])
            if att_used >= (max_att + extra_attempts):
                return False
    return True

@frappe.whitelist()
def get_learner_modules(filter_type="all"):
    """
    Returns modules assigned to the current learner, with their progress.
    filter_type: 'all' | 'mandatory' | 'optional'
    """
    user = frappe.session.user

    from lms.backend.api.common.module_detail import get_all_assigned_modules_for_learner
    assigned_rows = get_all_assigned_modules_for_learner(user)
    
    # Sort by creation desc to match original behavior
    assigned_rows.sort(key=lambda x: x.get("creation") or "", reverse=True)
    assignments = assigned_rows

    if filter_type == "mandatory":
        assignments = [a for a in assignments if a.is_mandatory]
    elif filter_type == "optional":
        assignments = [a for a in assignments if not a.is_mandatory]

    today_dt = getdate(today())
    results = []

    for a in assignments:
        module_doc = frappe.get_value(
            "LMS Module",
            a.module,
            ["module_name", "category", "status", "image"],
            as_dict=True
        )
        if not module_doc:
            continue

        if module_doc.status != 'Published':
            continue

        tracker = frappe.get_value(
            "LMS Module Tracker",
            {"user": user, "module": a.module},
            ["status", "progress_percentage", "started_on", "is_saved", "total_score"],
            as_dict=True
        )

        # Skip modules that have been explicitly unassigned (Unassigned sentinel)
        if tracker and tracker.status == "Unassigned":
            continue

        progress = (tracker.progress_percentage or 0) if tracker else 0

        # Days left calculation
        days_left = None
        is_overdue = False
        if a.duration and tracker and tracker.started_on:
            start = getdate(tracker.started_on)
            due_date = getdate(add_days(start, int(a.duration)))
            days_left = date_diff(due_date, today_dt)
            is_overdue = days_left < 0

        # Calculate completedCount and totalCount for module
        total_items = frappe.db.count("LMS Module Lesson Child", {"parent": a.module})
        completed_items = 0
        if tracker:
            progress_val = tracker.progress_percentage or 0
            completed_items = round(total_items * (progress_val / 100))

        # Calculate estimated duration from curriculum
        est_hours = get_estimated_hours_from_curriculum(a.module)
        if est_hours > 0:
            if est_hours < 1:
                duration_str = f"{int(est_hours * 60)} min"
            else:
                duration_str = f"{est_hours:g} hr"
        else:
            duration_str = "0 min"

        status = tracker.status if tracker else "Not Started"
        if status == "Failed":
            if not check_module_has_attempts_left(user, a.module):
                status = "Failed (No Attempts)"

        results.append({
            "id": a.module,
            "title": module_doc.module_name,
            "category": get_module_category(a.module),
            "type": "Module",
            "lessonsCount": frappe.db.count("LMS Module Lesson Child", {"parent": a.module}),
            "duration": duration_str,
            "daysLeft": days_left,
            "isOverdue": is_overdue,
            "completionRate": progress,
            "completedCount": completed_items,
            "totalCount": total_items,
            "status": status,
            "isRequired": bool(a.is_mandatory),
            "image": module_doc.image,
            "creation": a.get("creation", ""),
            "isSaved": bool(tracker.is_saved) if tracker else False,
            "score": float(tracker.total_score) if tracker and tracker.total_score is not None else 0.0
        })

    # Filter results based on filter_type
    if filter_type == "mandatory":
        results = [r for r in results if r["isRequired"]]
    elif filter_type == "optional":
        results = [r for r in results if not r["isRequired"]]

    # Sort results:
    # 1. Started modules ("Continue Learning") first
    # 2. Highest completionRate first
    # 3. Creation date (newest first)
    def sort_key(x):
        is_started = 1 if (x.get("status") and x.get("status").lower() != "not started") else 0
        progress = x.get("completionRate") or 0
        creation = x.get("creation") or ""
        return (is_started, progress, creation)
        
    results.sort(key=sort_key, reverse=True)

    return results


@frappe.whitelist()
def get_recommended_modules():
    """
    Returns unassigned modules from categories the learner has interacted with.
    """
    user = frappe.session.user

    # Get categories of assigned/tracked modules (from child table)
    assigned = frappe.db.sql("""
        SELECT DISTINCT mc.category
        FROM `tabLMS Module Category` mc
        INNER JOIN `tabLMS Module Assignment` ma ON ma.module = mc.parent
        INNER JOIN `tabLMS Assignment User` au ON au.parent = ma.name
        WHERE au.user = %s AND mc.category IS NOT NULL
    """, user, as_dict=True)
    categories = [a.category for a in assigned]

    if not categories:
        # Fallback to any unassigned if no history
        categories = frappe.db.sql("SELECT DISTINCT category FROM `tabLMS Module` WHERE category IS NOT NULL", as_dict=False)
        categories = [c[0] for c in categories] if categories else []

    # Get assigned module names to exclude
    assigned_names = frappe.db.sql("""
        SELECT DISTINCT ma.module
        FROM `tabLMS Module Assignment` ma
        INNER JOIN `tabLMS Assignment User` au ON au.parent = ma.name
        WHERE au.user = %s
    """, user, as_dict=False)
    assigned_names = [a[0] for a in assigned_names]

    # Fetch recommended — filter by category via child table
    filters = {"status": "Published"}
    if assigned_names:
        filters["name"] = ["not in", assigned_names]

    # If we have category matches, restrict to modules with those categories in child table
    if categories:
        matching_names = frappe.db.sql("""
            SELECT DISTINCT parent FROM `tabLMS Module Category`
            WHERE category IN %(cats)s AND parenttype = 'LMS Module'
        """, {"cats": categories}, as_dict=False)
        matching_names = [r[0] for r in matching_names]
        if matching_names:
            existing_name_filter = filters.get("name")
            if existing_name_filter:
                # intersect with existing not-in filter (exclude assigned, include matching)
                not_in_names = existing_name_filter[1] if isinstance(existing_name_filter, list) else []
                final_names = [n for n in matching_names if n not in not_in_names]
                filters["name"] = ["in", final_names] if final_names else ["in", ["__none__"]]
            else:
                filters["name"] = ["in", matching_names]

    modules = frappe.get_all(
        "LMS Module",
        filters=filters,
        fields=["name", "module_name", "category", "duration", "image"],
        limit=6,
        order_by="creation desc"
    )

    results = []
    if modules:
        module_names = [m.name for m in modules]
        trackers = frappe.get_all(
            "LMS Module Tracker",
            filters={"user": user, "module": ["in", module_names]},
            fields=["module", "is_saved"]
        )
        saved_map = {t.module: bool(t.is_saved) for t in trackers}
    else:
        saved_map = {}

    for m in modules:
        est_hours = get_estimated_hours_from_curriculum(m.name)
        if est_hours > 0:
            if est_hours < 1:
                duration_str = f"{int(est_hours * 60)} min"
            else:
                duration_str = f"{est_hours:g} hr"
        else:
            duration_str = "0 min"

        results.append({
            "id": m.name,
            "title": m.module_name,
            "category": get_module_category(m.name),
            "type": "Module",
            "lessonsCount": frappe.db.count("LMS Module Lesson Child", {"parent": m.name}),
            "duration": duration_str,
            "daysLeft": None,
            "isOverdue": False,
            "completionRate": 0,
            "status": "Not Started",
            "isRequired": False,
            "image": m.get("image"),
            "isSaved": saved_map.get(m.name, False),
        })
    return results

@frappe.whitelist()
def get_explore_modules():
    """
    Returns general popular or newest unassigned modules across the platform.
    """
    user = frappe.session.user

    assigned_names = frappe.db.sql("""
        SELECT DISTINCT ma.module
        FROM `tabLMS Module Assignment` ma
        INNER JOIN `tabLMS Assignment User` au ON au.parent = ma.name
        WHERE au.user = %s
    """, user, as_dict=False)
    assigned_names = [a[0] for a in assigned_names]

    filters = {"status": "Published"}
    if assigned_names:
        filters["name"] = ["not in", assigned_names]

    modules = frappe.get_all(
        "LMS Module",
        filters=filters,
        fields=["name", "module_name", "category", "duration", "image"],
        limit=6,
        order_by="creation desc"
    )

    results = []
    if modules:
        module_names = [m.name for m in modules]
        trackers = frappe.get_all(
            "LMS Module Tracker",
            filters={"user": user, "module": ["in", module_names]},
            fields=["module", "is_saved"]
        )
        saved_map = {t.module: bool(t.is_saved) for t in trackers}
    else:
        saved_map = {}

    for m in modules:
        est_hours = get_estimated_hours_from_curriculum(m.name)
        if est_hours > 0:
            if est_hours < 1:
                duration_str = f"{int(est_hours * 60)} min"
            else:
                duration_str = f"{est_hours:g} hr"
        else:
            duration_str = "0 min"

        results.append({
            "id": m.name,
            "title": m.module_name,
            "category": get_module_category(m.name),
            "type": "Module",
            "lessonsCount": frappe.db.count("LMS Module Lesson Child", {"parent": m.name}),
            "duration": duration_str,
            "daysLeft": None,
            "isOverdue": False,
            "completionRate": 0,
            "status": "Not Started",
            "isRequired": False,
            "image": m.get("image"),
            "isSaved": saved_map.get(m.name, False),
        })
    return results

@frappe.whitelist()
def get_learner_module_viewer_data(module_id):
    user = frappe.session.user
    
    # Check if published
    module = frappe.get_doc("LMS Module", module_id)
    if module.status != "Published":
        frappe.throw("Module is not published", frappe.PermissionError)
        
    # Check access (Assigned or Everyone)
    has_access = False
    if getattr(module, "module_view", "Everyone") == "Everyone":
        has_access = True
    else:
        from lms.backend.api.common.module_detail import get_all_assigned_modules_for_learner
        assigned_modules = get_all_assigned_modules_for_learner(user)
        for m in assigned_modules:
            if m["module"] == module_id:
                has_access = True
                break
                
    if not has_access and user != 'Administrator':
        roles = frappe.get_roles(user)
        if "LMS-TL" in roles or "LMS-Admin" in roles:
            has_access = True

    if not has_access and user != 'Administrator':
        frappe.throw("You do not have access to this module.", frappe.PermissionError)
        
    from lms.backend.api.admin.module_management import get_curriculum
    from lms.backend.api.common.module_detail import get_estimated_hours_from_curriculum
    
    # Metadata
    est_hours = get_estimated_hours_from_curriculum(module_id)
    if est_hours > 0:
        if est_hours < 1:
            duration_str = f"{int(est_hours * 60)} min"
        else:
            duration_str = f"{est_hours:g} hr"
    else:
        duration_str = "0 min"
        
    metadata = {
        "id": module.name,
        "title": module.module_name,
        "category": get_module_category(module.name),
        "lessonsCount": len(module.get("lessons", [])),
        "duration": duration_str,
        "dueDate": None,
        "isSaved": False,
        "isSequential": bool(module.get("is_sequential", 0)),
    }

    # Compute due_date from assignment if available
    assignment = frappe.db.sql("""
        SELECT ma.duration, mt.started_on
        FROM `tabLMS Module Assignment` ma
        LEFT JOIN `tabLMS Assignment User` au ON au.parent = ma.name AND au.user = %(user)s
        LEFT JOIN `tabLMS Module Tracker` mt ON mt.module = ma.module AND mt.user = %(user)s
        WHERE ma.module = %(module)s AND (au.user = %(user)s OR ma.name IS NOT NULL)
        LIMIT 1
    """, {"user": user, "module": module_id}, as_dict=True)

    if assignment and assignment[0].duration and assignment[0].started_on:
        from frappe.utils import add_days, getdate
        start = getdate(assignment[0].started_on)
        due = getdate(add_days(start, int(assignment[0].duration)))
        metadata["dueDate"] = str(due)

    # Curriculum
    curriculum = get_curriculum(module_id)
    
    # Trackers
    tracker = frappe.get_all(
        "LMS Module Tracker",
        filters={"user": user, "module": module_id},
        fields=["name", "status", "progress_percentage", "is_saved"],
        limit=1
    )
    
    progress_map = {}
    if tracker:
        t = tracker[0]
        metadata["isSaved"] = bool(t.is_saved)
        content_progress = frappe.get_all(
            "LMS Content Progress",
            filters={"parent": t.name},
            fields=["content_reference", "status", "score", "last_position"]
        )
        for cp in content_progress:
            progress_map[cp.content_reference] = {
                "status": cp.status,
                "score": cp.score,
                "last_position": cp.last_position
            }
            
    return {
        "metadata": metadata,
        "curriculum": curriculum,
        "overallProgress": tracker[0].progress_percentage if tracker else 0,
        "overallStatus": tracker[0].status if tracker else "Not started",
        "progressMap": progress_map
    }
