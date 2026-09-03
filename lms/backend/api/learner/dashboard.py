import frappe
from frappe.utils import today, add_days, add_months, getdate, date_diff
from lms.backend.api.common.module_detail import get_estimated_hours_from_curriculum

def get_module_category(module_name):
    """Fetch the first category from the LMS Module Category child table."""
    row = frappe.db.get_value(
        "LMS Module Category",
        {"parent": module_name, "parenttype": "LMS Module"},
        "category"
    )
    return row or "General"

# ─── Greeting ──────────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_learner_summary(timeframe="month"):
    """
    Returns a summary of the current learner's dashboard stats:
    - overall progress %, assigned modules, in-progress modules, badges
    """
    user = frappe.session.user

    # Modules assigned to this learner via LMS Module Assignment child table
    assigned_rows = frappe.db.sql("""
        SELECT DISTINCT ma.module, ma.duration
        FROM `tabLMS Module Assignment` ma
        INNER JOIN `tabLMS Assignment User` au ON au.parent = ma.name
        INNER JOIN `tabLMS Module` m ON m.name = ma.module
        WHERE au.user = %s AND m.status = 'Published'
    """, user, as_dict=True)
    explicitly_assigned = list(set([a.module for a in assigned_rows]))

    # Also include any module the user has started (has a tracker)
    all_trackers = frappe.get_all(
        "LMS Module Tracker",
        filters={"user": user},
        fields=["module", "status", "progress_percentage", "started_on"]
    )
    tracked_modules = [t.module for t in all_trackers]
    
    assigned_module_names = list(set(explicitly_assigned + tracked_modules))
    total_assigned = len(assigned_module_names)

    # Count learning paths even for users with no module assignments
    lp_trackers_early = []
    try:
        lp_trackers_early = frappe.get_all(
            "LMS Learning Path Tracker",
            filters={"user": user},
            fields=["learning_path"]
        )
    except frappe.exceptions.DoesNotExistError:
        pass
    except Exception as e:
        # If doctype is completely missing from db schema, it throws pymysql.err.ProgrammingError which frappe catches
        pass
    if not assigned_module_names:
        first_name = frappe.get_value("User", user, "first_name") or "Learner"
        lp_count = len(lp_trackers_early)
        return {
            "overallProgress": 0,
            "assignedModules": 0,
            "assignedLearningPaths": lp_count,
            "totalAssigned": lp_count,
            "inProgressModules": 0,
            "completedModules": 0,
            "badgesEarned": 0,
            "badgesThisMonth": 0,
            "firstName": first_name,
            "progressThisMonth": 0,
            "progressHistory": [0, 0, 0, 0, 0] if timeframe == "month" else [0] * 12,
            "progressLabels": ["Week 1", "Week 2", "Week 3", "Week 4", "Now"] if timeframe == "month" else ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
            "dueThisWeek": 0,
        }

    tracker_map = {t.module: t for t in all_trackers}
    completed = [m for m in assigned_module_names if tracker_map.get(m, {}).get("status") == "Completed"]
    in_progress = [m for m in assigned_module_names if tracker_map.get(m, {}).get("status") == "In Progress"]

    # Overall progress = average progress across all active modules
    total_progress = sum(
        (100 if tracker_map.get(m, {}).get("status") == "Completed" else (tracker_map.get(m, {}).get("progress_percentage") or 0)) 
        for m in assigned_module_names
    )
    overall_progress = int(total_progress / total_assigned) if total_assigned else 0

    # Badges (via LMS Learner Badge - uses 'user' field and 'awarded_on' date)
    badges = frappe.get_all(
        "LMS Learner Badge",
        filters={"user": user},
        fields=["badge", "awarded_on"]
    )
    badges_this_month_start = frappe.utils.get_first_day(today())
    badges_this_month = [b for b in badges if b.awarded_on and getdate(b.awarded_on) >= getdate(badges_this_month_start)]

    # Certificates
    certificates_earned = frappe.db.count("LMS Certificate", {"user": user})

    first_name = frappe.get_value("User", user, "first_name") or "Learner"

    # Learning Paths assigned to this learner
    # Attempt to fetch learning path trackers safely
    lp_trackers = []
    try:
        lp_trackers = frappe.get_all(
            "LMS Learning Path Tracker",
            filters={"user": user},
            fields=["learning_path"]
        )
    except Exception:
        pass
        
    total_learning_paths = len(list(set([lp.learning_path for lp in lp_trackers])))
    total_assigned = len(assigned_module_names) + total_learning_paths

    # Due this week (modules only)
    today_dt = getdate(today())
    due_this_week_count = 0
    modules_counted_as_due = set()
    
    for a in assigned_rows:
        if not a.duration or a.module in modules_counted_as_due:
            continue
        tracker = tracker_map.get(a.module, {})
        if tracker.get("status") == "Completed":
            continue
            
        start = getdate(tracker.get("started_on")) if tracker.get("started_on") else today_dt
        due_date = getdate(add_days(start, int(a.duration)))
        days_left = date_diff(due_date, today_dt)
        if 0 <= days_left <= 7:
            due_this_week_count += 1
            modules_counted_as_due.add(a.module)

    # Real progress history from LMS Module Tracker modification timestamps
    today_dt2 = getdate(today())
    # Build IN clause with one %s per module to avoid mixing positional/named params
    in_placeholders = ", ".join(["%s"] * len(assigned_module_names))

    import calendar
    from frappe.utils import now
    
    current_year = getdate(now()).year
    current_month = getdate(now()).month

    if timeframe == "year":
        intervals = [getdate(f"{current_year}-{m:02d}-28") for m in range(1, 13)]
        progress_labels = [getdate(dt).strftime("%b") for dt in intervals]
    else:
        num_days = calendar.monthrange(current_year, current_month)[1]
        intervals = [
            getdate(f"{current_year}-{current_month:02d}-07"),
            getdate(f"{current_year}-{current_month:02d}-14"),
            getdate(f"{current_year}-{current_month:02d}-21"),
            getdate(f"{current_year}-{current_month:02d}-{num_days}")
        ]
        progress_labels = [f"Week {i+1}" for i, dt in enumerate(intervals)]

    progress_history = []
    
    for period_end in intervals:
        if not assigned_module_names:
            progress_history.append(0)
            continue
            
        total_prog = frappe.db.sql(f"""
            SELECT COALESCE(SUM(progress_percentage), 0) as total
            FROM `tabLMS Module Tracker`
            WHERE user = %s AND module IN ({in_placeholders})
              AND DATE(modified) <= %s
        """, [user] + assigned_module_names + [str(period_end)], as_dict=True)
        t_prog = float(total_prog[0].total) if total_prog else 0.0
        snap = int(t_prog / total_assigned) if total_assigned else 0
        progress_history.append(snap)
        
    if timeframe == "year":
        progress_this_month = max(0, progress_history[-1] - (progress_history[-2] if len(progress_history) > 1 else 0))
    else:
        progress_this_month = max(0, progress_history[-1] - progress_history[0])

    # Calculate Average Score
    avg_score_res = frappe.db.sql("""
        SELECT AVG(score) as avg_score
        FROM `tabLMS Quiz Submission`
        WHERE user = %s
    """, user, as_dict=True)
    average_score = round(avg_score_res[0].avg_score or 0)

    # Calculate Recently Completed Modules
    recently_completed = []
    recent_trackers = frappe.get_all(
        "LMS Module Tracker",
        filters={"user": user, "status": "Completed"},
        fields=["module", "modified", "name"],
        order_by="modified desc",
        limit=3
    )
    for t in recent_trackers:
        module_title = frappe.get_value("LMS Module", t.module, "module_name")
        latest_quiz = frappe.get_all(
            "LMS Quiz Submission",
            filters={"enrollment": t.name},
            fields=["score"],
            order_by="submitted_on desc",
            limit=1
        )
        # If no quiz, assume 100% since it's completed (or leave as N/A, but 100 is better for UI)
        score = round(latest_quiz[0].score) if latest_quiz else 100
        
        recently_completed.append({
            "id": t.module,
            "title": module_title,
            "completedDate": frappe.utils.getdate(t.modified).strftime("%b %d"),
            "score": score
        })
    return {
        "overallProgress": overall_progress,
        "assignedModules": len(assigned_module_names),
        "assignedLearningPaths": total_learning_paths,
        "totalAssigned": total_assigned,
        "inProgressModules": len(in_progress),
        "completedModules": len(completed),
        "badgesEarned": len(badges),
        "badgesThisMonth": len(badges_this_month),
        "certificatesEarned": certificates_earned,
        "firstName": first_name,
        "progressThisMonth": progress_this_month,
        "progressHistory": progress_history,
        "progressLabels": progress_labels,
        "dueThisWeek": due_this_week_count,
        "averageScore": average_score,
        "recentlyCompleted": recently_completed,
    }


# ─── Continue Learning ─────────────────────────────────────────────────────────

@frappe.whitelist()
def get_continue_learning():
    """
    Returns the best module to resume for the learner.
    Priority:
      1. Most recently modified In Progress module (never Completed)
      2. First assigned module that is Not Started yet (no tracker at all)
    Completed modules are never shown.
    """
    user = frappe.session.user

    # Priority 1: most recently modified In Progress module
    tracker = frappe.db.sql("""
        SELECT t.module, t.progress_percentage, t.modified
        FROM `tabLMS Module Tracker` t
        WHERE t.user = %s AND t.status = 'In Progress'
        ORDER BY t.modified DESC
        LIMIT 1
    """, user, as_dict=True)

    if tracker:
        t = tracker[0]
    else:
        # Priority 2: first assigned module the user hasn't started at all
        not_started = frappe.db.sql("""
            SELECT ma.module
            FROM `tabLMS Module Assignment` ma
            INNER JOIN `tabLMS Assignment User` au ON au.parent = ma.name
            LEFT JOIN `tabLMS Module Tracker` t ON t.module = ma.module AND t.user = %s
            WHERE au.user = %s
              AND (t.name IS NULL OR t.status NOT IN ('In Progress', 'Completed'))
            ORDER BY ma.creation ASC
            LIMIT 1
        """, (user, user), as_dict=True)

        if not not_started:
            return None

        t = frappe._dict({"module": not_started[0].module, "progress_percentage": 0})


    module_doc = frappe.get_value("LMS Module", t.module, ["module_name", "image"], as_dict=True)
    if not module_doc:
        return None

    # Count lessons from the child link table
    total_lessons = frappe.db.count("LMS Module Lesson Child", {"parent": t.module})

    # Find which module number this is in the assigned sequence
    assigned = frappe.db.sql("""
        SELECT DISTINCT ma.module, ma.creation
        FROM `tabLMS Module Assignment` ma
        INNER JOIN `tabLMS Assignment User` au ON au.parent = ma.name
        INNER JOIN `tabLMS Module` m ON m.name = ma.module
        WHERE au.user = %s AND m.status = 'Published'
        ORDER BY ma.creation ASC
    """, user, as_dict=True)
    module_index = next((i + 1 for i, a in enumerate(assigned) if a.module == t.module), 1)
    total_modules = len(assigned) or 1

    return {
        "moduleId": t.module,
        "moduleName": module_doc.module_name,
        "progress": t.progress_percentage or 0,
        "moduleIndex": module_index,
        "totalModules": total_modules,
        "totalLessons": total_lessons,
        "thumbnail": module_doc.image,
    }
