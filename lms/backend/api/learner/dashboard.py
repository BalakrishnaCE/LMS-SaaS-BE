import frappe
from frappe.utils import today, add_days, getdate, date_diff

# ─── Greeting ──────────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_learner_summary():
    """
    Returns a summary of the current learner's dashboard stats:
    - overall progress %, assigned modules, in-progress modules, badges
    """
    user = frappe.session.user

    # Modules assigned to this learner via LMS Module Assignment
    assigned_modules = frappe.get_all(
        "LMS Module Assignment",
        filters={"learner": user},
        fields=["module"],
        distinct=True
    )
    assigned_module_names = [a.module for a in assigned_modules]

    total_assigned = len(assigned_module_names)

    if not assigned_module_names:
        return {
            "overallProgress": 0,
            "assignedModules": 0,
            "inProgressModules": 0,
            "completedModules": 0,
            "badgesEarned": 0,
            "badgesThisMonth": 0,
            "firstName": frappe.get_value("User", user, "first_name") or "Learner"
        }

    # Get trackers for this learner
    trackers = frappe.get_all(
        "LMS Module Tracker",
        filters={"learner": user, "module": ["in", assigned_module_names]},
        fields=["module", "status", "progress"]
    )

    tracker_map = {t.module: t for t in trackers}
    completed = [m for m in assigned_module_names if tracker_map.get(m, {}).get("status") == "Completed"]
    in_progress = [m for m in assigned_module_names if tracker_map.get(m, {}).get("status") == "In Progress"]

    # Overall progress = average progress across all assigned modules
    total_progress = sum(
        (tracker_map.get(m, {}).get("progress") or 0) for m in assigned_module_names
    )
    overall_progress = int(total_progress / total_assigned) if total_assigned else 0

    # Badges (via LMS Badge Assignment)
    badges = frappe.get_all(
        "LMS Badge Assignment",
        filters={"learner": user},
        fields=["badge", "creation"]
    )
    badges_this_month_start = frappe.utils.get_first_day(today())
    badges_this_month = [b for b in badges if getdate(b.creation) >= getdate(badges_this_month_start)]

    first_name = frappe.get_value("User", user, "first_name") or "Learner"

    return {
        "overallProgress": overall_progress,
        "assignedModules": total_assigned,
        "inProgressModules": len(in_progress),
        "completedModules": len(completed),
        "badgesEarned": len(badges),
        "badgesThisMonth": len(badges_this_month),
        "firstName": first_name,
    }


# ─── Continue Learning ─────────────────────────────────────────────────────────

@frappe.whitelist()
def get_continue_learning():
    """
    Returns the most recently accessed in-progress module for the learner.
    """
    user = frappe.session.user

    tracker = frappe.get_all(
        "LMS Module Tracker",
        filters={"learner": user, "status": "In Progress"},
        fields=["module", "progress", "modified"],
        order_by="modified desc",
        limit=1
    )

    if not tracker:
        return None

    t = tracker[0]
    module_doc = frappe.get_value("LMS Module", t.module, ["module_name", "total_lessons"], as_dict=True)
    if not module_doc:
        return None

    # Find which module number this is in assigned sequence
    assigned = frappe.get_all(
        "LMS Module Assignment",
        filters={"learner": user},
        fields=["module"],
        order_by="creation asc"
    )
    module_index = next((i + 1 for i, a in enumerate(assigned) if a.module == t.module), 1)
    total_modules = len(assigned)

    return {
        "moduleId": t.module,
        "moduleName": module_doc.module_name,
        "progress": t.progress or 0,
        "moduleIndex": module_index,
        "totalModules": total_modules,
    }


# ─── Progress Breakdown ────────────────────────────────────────────────────────

@frappe.whitelist()
def get_learner_progress_breakdown():
    """
    Returns progress statistics broken down by status for the learner.
    """
    user = frappe.session.user

    assigned_modules = frappe.get_all(
        "LMS Module Assignment",
        filters={"learner": user},
        fields=["module", "duration"],
        distinct=True
    )
    assigned_module_names = [a.module for a in assigned_modules]
    total = len(assigned_module_names)

    if not total:
        return {
            "overallProgress": 0,
            "stats": [
                {"label": "Passed", "value": "0%"},
                {"label": "Failed", "value": "0%"},
                {"label": "Overdue", "value": "0%"},
                {"label": "In Progress", "value": "0%"},
                {"label": "Not Started", "value": "0%"},
            ]
        }

    trackers = frappe.get_all(
        "LMS Module Tracker",
        filters={"learner": user, "module": ["in", assigned_module_names]},
        fields=["module", "status", "progress", "started_on"]
    )
    tracker_map = {t.module: t for t in trackers}
    assignment_map = {a.module: a for a in assigned_modules}

    today_dt = getdate(today())
    counts = {"Passed": 0, "Failed": 0, "Overdue": 0, "In Progress": 0, "Not Started": 0}

    for module_name in assigned_module_names:
        t = tracker_map.get(module_name)
        a = assignment_map.get(module_name)

        if not t:
            # Check if overdue
            if a and a.duration and assigned_modules[0]:
                counts["Not Started"] += 1
            else:
                counts["Not Started"] += 1
            continue

        status = t.status
        if status == "Completed":
            # Determine pass/fail from assessment score if available
            score = frappe.db.get_value(
                "LMS Assessment Result",
                {"learner": user, "module": module_name},
                "score"
            )
            passing_score = frappe.db.get_value("LMS Module", module_name, "passing_score") or 60
            if score is not None:
                counts["Passed" if score >= passing_score else "Failed"] += 1
            else:
                counts["Passed"] += 1
        elif status == "In Progress":
            # Check if overdue
            if a and a.duration and t.started_on:
                due_date = getdate(add_days(getdate(t.started_on), int(a.duration)))
                if due_date < today_dt:
                    counts["Overdue"] += 1
                else:
                    counts["In Progress"] += 1
            else:
                counts["In Progress"] += 1
        else:
            counts["Not Started"] += 1

    def pct(n):
        return f"{round((n / total) * 100)}%" if total else "0%"

    # Overall progress = total passed / total * 100
    overall = round(((counts["Passed"]) / total) * 100) if total else 0

    return {
        "overallProgress": overall,
        "stats": [
            {"label": "Passed", "value": pct(counts["Passed"])},
            {"label": "Failed", "value": pct(counts["Failed"])},
            {"label": "Overdue", "value": pct(counts["Overdue"])},
            {"label": "In Progress", "value": pct(counts["In Progress"])},
            {"label": "Not Started", "value": pct(counts["Not Started"])},
        ]
    }


# ─── Upcoming Deadlines (Learner-scoped) ───────────────────────────────────────

@frappe.whitelist()
def get_learner_deadlines():
    """
    Returns upcoming deadlines for the current learner's assigned modules.
    """
    user = frappe.session.user

    assignments = frappe.get_all(
        "LMS Module Assignment",
        filters={"learner": user},
        fields=["module", "duration"]
    )

    today_dt = getdate(today())
    results = []

    for a in assignments:
        if not a.duration:
            continue

        tracker = frappe.get_value(
            "LMS Module Tracker",
            {"learner": user, "module": a.module},
            ["started_on", "status"],
            as_dict=True
        )

        if not tracker or tracker.status == "Completed":
            continue

        start = getdate(tracker.started_on) if tracker and tracker.started_on else today_dt
        due_date = getdate(add_days(start, int(a.duration)))

        days_left = date_diff(due_date, today_dt)
        if days_left < 0 or days_left > 30:
            continue

        module_name = frappe.get_value("LMS Module", a.module, "module_name") or a.module

        results.append({
            "id": a.module,
            "title": module_name,
            "dueDate": f"Due {due_date.strftime('%b %d')}",
            "daysLeft": f"{abs(days_left)} days {'overdue' if days_left < 0 else 'left'}",
            "isOverdue": days_left < 0,
            "isUrgent": 0 <= days_left <= 3,
        })

    return sorted(results, key=lambda x: x["daysLeft"])[:5]


# ─── Required / Assigned Modules ───────────────────────────────────────────────

@frappe.whitelist()
def get_learner_modules(filter_type="all"):
    """
    Returns modules assigned to the current learner, with their progress.
    filter_type: 'all' | 'mandatory' | 'optional'
    """
    user = frappe.session.user

    filters = {"learner": user}
    if filter_type == "mandatory":
        filters["is_mandatory"] = 1
    elif filter_type == "optional":
        filters["is_mandatory"] = 0

    assignments = frappe.get_all(
        "LMS Module Assignment",
        filters=filters,
        fields=["module", "duration", "is_mandatory"],
        order_by="creation desc"
    )

    today_dt = getdate(today())
    results = []

    for a in assignments:
        module_doc = frappe.get_value(
            "LMS Module",
            a.module,
            ["module_name", "category", "total_lessons", "status"],
            as_dict=True
        )
        if not module_doc:
            continue

        tracker = frappe.get_value(
            "LMS Module Tracker",
            {"learner": user, "module": a.module},
            ["status", "progress", "started_on"],
            as_dict=True
        )

        progress = (tracker.progress or 0) if tracker else 0

        # Days left calculation
        days_left = None
        is_overdue = False
        if a.duration:
            start = getdate(tracker.started_on) if tracker and tracker.started_on else today_dt
            due_date = getdate(add_days(start, int(a.duration)))
            days_left = date_diff(due_date, today_dt)
            is_overdue = days_left < 0

        results.append({
            "id": a.module,
            "title": module_doc.module_name,
            "category": module_doc.category or "General",
            "type": "Module",
            "lessonsCount": module_doc.total_lessons or 0,
            "duration": f"{a.duration} days" if a.duration else "No limit",
            "daysLeft": days_left,
            "isOverdue": is_overdue,
            "completionRate": progress,
            "status": (tracker.status if tracker else "Not Started"),
            "isRequired": bool(a.is_mandatory),
        })

    return results


# ─── Badges ────────────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_learner_badges():
    """Returns badges earned by the current learner."""
    user = frappe.session.user

    badges = frappe.get_all(
        "LMS Badge Assignment",
        filters={"learner": user},
        fields=["badge", "creation"],
        order_by="creation desc",
        limit=10
    )

    results = []
    for b in badges:
        badge_doc = frappe.get_value("LMS Badge", b.badge, ["badge_name", "description", "image"], as_dict=True)
        if not badge_doc:
            continue
        results.append({
            "id": b.badge,
            "name": badge_doc.badge_name,
            "description": badge_doc.description,
            "image": badge_doc.image,
            "earnedOn": str(b.creation),
        })

    return results

# ─── Legacy Admin Endpoints (DO NOT REMOVE - used by Admin Dashboard) ────────

@frappe.whitelist(allow_guest=True)
def get_upcoming_deadlines():
    assignments = frappe.get_all("LMS Module Assignment", fields=["name", "module", "duration", "is_mandatory"])
    assignment_map = {a.module: a for a in assignments}
    
    approaching = {}
    today_dt = getdate(today())
    next_week = getdate(add_days(today_dt, 30))
    
    trackers = frappe.get_all("LMS Module Tracker", filters={"status": ["!=", "Completed"]}, fields=["module", "started_on"])
    for t in trackers:
        if not t.started_on:
            continue
        a = assignment_map.get(t.module)
        if a and a.duration:
            due = getdate(add_days(getdate(t.started_on), a.duration))
            if today_dt <= due <= next_week:
                if t.module not in approaching:
                    approaching[t.module] = {"count": 0, "mandatory": a.is_mandatory}
                approaching[t.module]["count"] += 1
                
    results = []
    for module_name, data in approaching.items():
        results.append({
            "id": module_name,
            "name": module_name,
            "type": "Module",
            "date": "Approaching in 30 days",
            "pending": data['count'],
            "critical": bool(data['mandatory'])
        })
        
    return sorted(results, key=lambda x: x["pending"], reverse=True)[:5]

@frappe.whitelist(allow_guest=True)
def get_recently_assigned():
    assignments = frappe.get_all("LMS Module Assignment", 
        fields=["name", "module", "creation", "duration"],
        limit=20,
        order_by="creation desc"
    )
    
    seen_modules = set()
    unique_assignments = []
    for a in assignments:
        if a.module not in seen_modules:
            seen_modules.add(a.module)
            unique_assignments.append(a)
        if len(unique_assignments) == 5:
            break
            
    results = []
    for a in unique_assignments:
        trackers = frappe.get_all("LMS Module Tracker", filters={"module": a.module}, fields=["status"])
        total_assigned = len(trackers)
        completed = len([t for t in trackers if t.status == "Completed"])
        progress = int((completed / total_assigned) * 100) if total_assigned > 0 else 0
        
        results.append({
            "id": a.name,
            "name": a.module,
            "assignedLearners": total_assigned,
            "dueDate": f"{a.duration} Days" if a.duration else "No Limit",
            "progress": progress,
            "actions": ["View Progress", "Send Reminder"]
        })
    return results
