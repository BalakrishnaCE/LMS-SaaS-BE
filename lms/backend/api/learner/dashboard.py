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
    # LMS Module Assignment stores learners in child table 'LMS Assignment User' with field 'user'
    assigned_rows = frappe.db.sql("""
        SELECT DISTINCT ma.module, ma.duration
        FROM `tabLMS Module Assignment` ma
        INNER JOIN `tabLMS Assignment User` au ON au.parent = ma.name
        INNER JOIN `tabLMS Module` m ON m.name = ma.module
        WHERE au.user = %s AND m.status = 'Published'
    """, user, as_dict=True)
    assigned_module_names = list(set([a.module for a in assigned_rows]))

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

    # Get trackers for this learner (LMS Module Tracker uses 'user' not 'learner')
    trackers = frappe.get_all(
        "LMS Module Tracker",
        filters={"user": user, "module": ["in", assigned_module_names]},
        fields=["module", "status", "progress_percentage", "started_on"]
    )

    tracker_map = {t.module: t for t in trackers}
    completed = [m for m in assigned_module_names if tracker_map.get(m, {}).get("status") == "Completed"]
    in_progress = [m for m in assigned_module_names if tracker_map.get(m, {}).get("status") == "In Progress"]

    # Overall progress = average progress across all assigned modules
    total_progress = sum(
        (tracker_map.get(m, {}).get("progress_percentage") or 0) for m in assigned_module_names
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
    
    for a in assigned_rows:
        if not a.duration:
            continue
        tracker = tracker_map.get(a.module, {})
        if tracker.get("status") == "Completed":
            continue
            
        start = getdate(tracker.get("started_on")) if tracker.get("started_on") else today_dt
        due_date = getdate(add_days(start, int(a.duration)))
        days_left = date_diff(due_date, today_dt)
        if 0 <= days_left <= 7:
            due_this_week_count += 1

    # Real progress history from LMS Module Tracker modification timestamps
    today_dt2 = getdate(today())
    # Build IN clause with one %s per module to avoid mixing positional/named params
    in_placeholders = ", ".join(["%s"] * len(assigned_module_names))

    if timeframe == "year":
        progress_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        progress_history = []
        for month_offset in range(11, -1, -1):
            period_end = getdate(add_months(today_dt2, -month_offset))
            total_prog = frappe.db.sql(f"""
                SELECT COALESCE(SUM(progress_percentage), 0) as total
                FROM `tabLMS Module Tracker`
                WHERE user = %s AND module IN ({in_placeholders})
                  AND DATE(modified) <= %s
            """, [user] + assigned_module_names + [str(period_end)], as_dict=True)
            t_prog = float(total_prog[0].total) if total_prog else 0.0
            snap = int(t_prog / total_assigned) if total_assigned else 0
            progress_history.append(snap)
        progress_history = progress_history[::-1]
        progress_this_month = max(0, progress_history[-1] - (progress_history[-2] if len(progress_history) > 1 else 0))
    else:
        # Weekly: 4 past weeks + current
        progress_labels = ["Week 1", "Week 2", "Week 3", "Week 4", "Now"]
        progress_history = []
        for week_offset in range(4, -1, -1):
            period_end = getdate(add_days(today_dt2, -(week_offset * 7)))
            total_prog = frappe.db.sql(f"""
                SELECT COALESCE(SUM(progress_percentage), 0) as total
                FROM `tabLMS Module Tracker`
                WHERE user = %s AND module IN ({in_placeholders})
                  AND DATE(modified) <= %s
            """, [user] + assigned_module_names + [str(period_end)], as_dict=True)
            t_prog = float(total_prog[0].total) if total_prog else 0.0
            snap = int(t_prog / total_assigned) if total_assigned else 0
            progress_history.append(snap)
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
    Returns the most recently accessed in-progress module for the learner.
    """
    user = frappe.session.user

    tracker = frappe.db.sql("""
        SELECT t.module, t.progress_percentage, t.modified
        FROM `tabLMS Module Tracker` t
        INNER JOIN `tabLMS Module` m ON m.name = t.module
        WHERE t.user = %s AND t.status = 'In Progress' AND m.status = 'Published'
        ORDER BY t.modified DESC
        LIMIT 1
    """, user, as_dict=True)

    if not tracker:
        assigned = frappe.db.sql("""
            SELECT ma.module, ma.creation
            FROM `tabLMS Module Assignment` ma
            INNER JOIN `tabLMS Assignment User` au ON au.parent = ma.name
            INNER JOIN `tabLMS Module` m ON m.name = ma.module
            WHERE au.user = %s AND m.status = 'Published'
            ORDER BY ma.creation ASC
            LIMIT 1
        """, user, as_dict=True)
        if not assigned:
            return None
        t = frappe._dict({"module": assigned[0].module, "progress_percentage": 0})
    else:
        t = tracker[0]
    module_doc = frappe.get_value("LMS Module", t.module, ["module_name", "image"], as_dict=True)
    if not module_doc:
        return None

    # Count lessons from the child link table
    total_lessons = frappe.db.count("LMS Module Lesson Child", {"parent": t.module})

    # Find which module number this is in assigned sequence
    assigned = frappe.db.sql("""
        SELECT DISTINCT ma.module, ma.creation
        FROM `tabLMS Module Assignment` ma
        INNER JOIN `tabLMS Assignment User` au ON au.parent = ma.name
        INNER JOIN `tabLMS Module` m ON m.name = ma.module
        WHERE au.user = %s AND m.status = 'Published'
        ORDER BY ma.creation ASC
    """, user, as_dict=True)
    module_index = next((i + 1 for i, a in enumerate(assigned) if a.module == t.module), 1)
    total_modules = len(assigned)

    return {
        "moduleId": t.module,
        "moduleName": module_doc.module_name,
        "progress": t.progress_percentage or 0,
        "moduleIndex": module_index,
        "totalModules": total_modules or 1,
        "totalLessons": total_lessons,
        "thumbnail": module_doc.image,
    }




