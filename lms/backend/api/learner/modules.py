import frappe
from frappe.utils import today, add_days, getdate, date_diff
from lms.backend.api.common.module_detail import get_estimated_hours_from_curriculum
from lms.backend.api.learner.dashboard import get_module_category

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
            ["status", "progress_percentage", "started_on"],
            as_dict=True
        )

        # Skip modules that have been explicitly unassigned (Excluded sentinel)
        if tracker and tracker.status == "Excluded":
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

        # Calculate completedCount and totalCount for module (completed lessons vs total lessons)
        total_items = frappe.db.count("LMS Module Lesson Child", {"parent": a.module})
        completed_items = 0
        if tracker:
            # Count completed lessons (matching lesson-level, not content-block-level)
            tracker_name = frappe.db.get_value("LMS Module Tracker", {"user": user, "module": a.module}, "name")
            if tracker_name:
                completed_items = frappe.db.sql(
                    "SELECT count(name) FROM `tabLMS Lesson Progress` WHERE parent = %s AND status = 'Completed'",
                    tracker_name
                )[0][0]

        # Calculate estimated duration from curriculum
        est_hours = get_estimated_hours_from_curriculum(a.module)
        if est_hours > 0:
            if est_hours < 1:
                duration_str = f"{int(est_hours * 60)} min"
            else:
                duration_str = f"{est_hours:g} hr"
        else:
            duration_str = "0 min"

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
            "status": (tracker.status if tracker else "Not Started"),
            "isRequired": bool(a.is_mandatory),
            "image": module_doc.image,
            "creation": a.get("creation", "")
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
        fields=["name", "module_name", "category", "duration"],
        limit=6,
        order_by="creation desc"
    )

    results = []
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
        fields=["name", "module_name", "category", "duration"],
        limit=6,
        order_by="creation desc"
    )

    results = []
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

    if assignment and assignment[0].duration:
        from frappe.utils import add_days, getdate, today
        start = getdate(assignment[0].started_on) if assignment[0].started_on else getdate(today())
        due = getdate(add_days(start, int(assignment[0].duration)))
        metadata["dueDate"] = str(due)

    # Curriculum
    curriculum = get_curriculum(module_id)
    
    # Trackers
    tracker = frappe.get_all(
        "LMS Module Tracker",
        filters={"user": user, "module": module_id},
        fields=["name", "status", "progress_percentage"],
        limit=1
    )
    
    progress_map = {}
    if tracker:
        t = tracker[0]
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
