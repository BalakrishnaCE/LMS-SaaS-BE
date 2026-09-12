import frappe
from frappe.utils import today, add_days, add_months, getdate, date_diff
from lms.backend.api.common.module_detail import (
    get_estimated_hours_from_curriculum, 
    get_all_assigned_modules_for_learner
)

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
    from lms.backend.api.common.module_detail import get_all_assigned_modules_for_learner
    assigned_rows = get_all_assigned_modules_for_learner(user)
    explicitly_assigned = list(set([a["module"] for a in assigned_rows]))

    # Also include any module the user has started (has a tracker)
    all_trackers = frappe.get_all(
        "LMS Module Tracker",
        filters={"user": user},
        fields=["module", "status", "progress_percentage", "started_on"]
    )
    # Exclude sentinel 'Excluded' trackers written by the admin unassign action
    all_trackers = [t for t in all_trackers if t.status != "Excluded"]
    tracked_modules = [t.module for t in all_trackers]
    
    assigned_module_names = list(set(explicitly_assigned + tracked_modules))
    # Also exclude modules that have been explicitly unassigned for this user
    excluded_modules = frappe.db.sql("""
        SELECT module FROM `tabLMS Module Tracker`
        WHERE user = %s AND status = 'Excluded'
    """, user, as_list=True)
    excluded_set = {row[0] for row in excluded_modules}
    assigned_module_names = [m for m in assigned_module_names if m not in excluded_set]
    total_assigned = len(assigned_module_names)


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
            fields=["learning_path", "status"]
        )
    except Exception:
        pass
        
    total_learning_paths = len(list(set([lp.learning_path for lp in lp_trackers])))
    in_progress_paths = len([lp for lp in lp_trackers if lp.status == "In Progress"])
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
        # Delta from start of year to now (first non-zero vs last)
        first = progress_history[0] if progress_history else 0
        last = progress_history[-1] if progress_history else 0
        progress_this_month = last - first
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
        "inProgressPaths": in_progress_paths,
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
def get_continue_learning(item_type="module"):
    """
    Returns the best module or path to resume for the learner.
    Priority:
      1. Most progressed In Progress item
      2. First assigned item that is Not Started yet
    item_type can be 'module', 'path', or 'both'.
    """
    user = frappe.session.user

    # Priority 1: In Progress item with highest progress percentage
    queries = []
    params = []
    
    if item_type in ["module", "both"]:
        queries.append("""
            SELECT 'Module' as type, t.module as id, t.progress_percentage, t.modified
            FROM `tabLMS Module Tracker` t
            INNER JOIN `tabLMS Module` m ON m.name = t.module
            WHERE t.user = %s AND t.status = 'In Progress' AND m.status = 'Published'
        """)
        params.append(user)
        
    if item_type in ["path", "both"]:
        queries.append("""
            SELECT 'Path' as type, t.learning_path as id, t.progress_percentage, t.modified
            FROM `tabLMS Learning Path Tracker` t
            INNER JOIN `tabLMS Learning Path` lp ON lp.name = t.learning_path
            WHERE t.user = %s AND t.status = 'In Progress' AND lp.status = 'Published'
        """)
        params.append(user)
        
    if not queries:
        return None
        
    union_query = " UNION ALL ".join(queries) + " ORDER BY progress_percentage DESC, modified DESC LIMIT 1"
    tracker = frappe.db.sql(union_query, tuple(params), as_dict=True)

    if tracker:
        t = tracker[0]
    else:
        # Priority 2: first assigned item the user hasn't started at all
        not_started_queries = []
        ns_params = []
        
        if item_type in ["module", "both"]:
            not_started_queries.append("""
                SELECT 'Module' as type, ma.module as id, ma.creation
                FROM `tabLMS Module Assignment` ma
                INNER JOIN `tabLMS Module` m ON m.name = ma.module
                INNER JOIN `tabLMS Assignment User` au ON au.parent = ma.name
                LEFT JOIN `tabLMS Module Tracker` t ON t.module = ma.module AND t.user = %s
                WHERE au.user = %s
                  AND m.status = 'Published'
                  AND (t.name IS NULL OR t.status NOT IN ('In Progress', 'Completed'))
            """)
            ns_params.extend([user, user])
            
        if item_type in ["path", "both"]:
            not_started_queries.append("""
                SELECT 'Path' as type, lp.name as id, lp.creation
                FROM `tabLMS Learning Path` lp
                LEFT JOIN `tabLMS Learning Path Tracker` t ON t.learning_path = lp.name AND t.user = %s
                WHERE lp.status = 'Published'
                  AND (t.name IS NULL OR t.status NOT IN ('In Progress', 'Completed'))
            """)
            ns_params.append(user)
            
        union_ns_query = " UNION ALL ".join(not_started_queries) + " ORDER BY creation ASC LIMIT 1"
        not_started = frappe.db.sql(union_ns_query, tuple(ns_params), as_dict=True)
        
        if not_started:
            t = not_started[0]
        else:
            return None

    if t.type == 'Module':
        module_doc = frappe.get_value("LMS Module", t.id, ["module_name", "image"], as_dict=True)
        if not module_doc:
            return None
        
        return {
            "moduleId": t.id,
            "moduleName": module_doc.module_name,
            "moduleIndex": 1,
            "totalModules": 1,
            "progress": int(t.get("progress_percentage") or 0),
            "thumbnail": module_doc.image,
            "type": "Module"
        }
    else:
        path_doc = frappe.get_value("LMS Learning Path", t.id, ["path_name", "image"], as_dict=True)
        if not path_doc:
            return None
            
        return {
            "moduleId": t.id,
            "moduleName": path_doc.path_name,
            "moduleIndex": 1,
            "totalModules": 1,
            "progress": int(t.get("progress_percentage") or 0),
            "thumbnail": path_doc.image,
            "type": "Path"
        }

