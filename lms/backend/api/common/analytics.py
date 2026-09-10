import frappe
import calendar
from collections import defaultdict
from frappe.utils import today, add_days, getdate, add_months, now
from lms.backend.api.manager.metrics import _get_team_member_emails

def _get_filter_for_user():
    user = frappe.session.user
    roles = frappe.get_roles(user)
    
    if "System Manager" in roles or "LMS Admin" in roles:
        return None # No filter, return all
        
    if "LMS Manager" in roles:
        member_emails = _get_team_member_emails(user)
        if not member_emails:
            return [] # Returns empty list to indicate no data
        return member_emails
        
    return [] # Default fallback

@frappe.whitelist(allow_guest=True)
def get_metrics_summary():
    user_filter = _get_filter_for_user()
    if user_filter == []:
        return {"month": {}, "year": {}}

    def get_data(timeframe):
        current_year = getdate(now()).year
        current_month = getdate(now()).month
        
        if timeframe == "year":
            intervals = [getdate(f"{current_year}-{m:02d}-28") for m in range(1, 13)]
        else:
            num_days = calendar.monthrange(current_year, current_month)[1]
            intervals = [
                getdate(f"{current_year}-{current_month:02d}-07"),
                getdate(f"{current_year}-{current_month:02d}-14"),
                getdate(f"{current_year}-{current_month:02d}-21"),
                getdate(f"{current_year}-{current_month:02d}-{num_days}")
            ]
        
        active_learners_history = []
        completion_rate_history = []
        overdue_assignments_history = []
        compliance_completion_history = []
        
        assignments = frappe.get_all("LMS Module Assignment", fields=["name", "module", "duration", "creation", "is_mandatory"])
        assignment_map = {a.module: a for a in assignments}
        
        all_module_categories = frappe.get_all("LMS Module Category", fields=["parent", "category"])
        module_categories_map = {}
        for mc in all_module_categories:
            if mc.parent not in module_categories_map:
                module_categories_map[mc.parent] = set()
            module_categories_map[mc.parent].add(mc.category)
        
        # Filter learners based on user_filter
        learner_filters = {"role": "LMS-Learner"}
        if user_filter is None:
            pass # no extra filter
        else:
            learner_filters["parent"] = ["in", user_filter]
            
        all_learner_roles = frappe.get_all("Has Role", filters=learner_filters, fields=["parent", "creation"])
        
        def compute_metrics_for_date(dt):
            learners_by_dt = set([r.parent for r in all_learner_roles if getdate(r.creation) <= getdate(dt)])
            thirty_days_before_dt = add_days(dt, -30)
            
            tracker_filters = {"creation": ["<=", dt]}
            if user_filter is not None:
                tracker_filters["user"] = ["in", user_filter]
                
            trackers_dt = frappe.get_all("LMS Module Tracker", filters=tracker_filters, fields=["status", "modified", "module", "started_on", "creation", "completed_on", "user"])
            
            active_users_at_dt = set()
            for t in trackers_dt:
                if t.modified and getdate(thirty_days_before_dt) <= getdate(t.modified) <= getdate(dt):
                    if t.user in learners_by_dt:
                        active_users_at_dt.add(t.user)
            active_learners_val = len(active_users_at_dt)
            
            total_dt = len(trackers_dt)
            completed_dt = 0
            overdue_dt = 0
            
            for t in trackers_dt:
                is_completed_by_dt = (t.status == "Completed" and (not t.completed_on or getdate(t.completed_on) <= getdate(dt)))
                if is_completed_by_dt:
                    completed_dt += 1
                
                a = assignment_map.get(t.module)
                if a and a.duration and t.started_on:
                    start_date = getdate(t.started_on)
                    due_date = add_days(start_date, a.duration)
                    is_completed_on_time = (t.status == "Completed" and (not t.completed_on or getdate(t.completed_on) <= getdate(dt)))
                    if getdate(due_date) < getdate(dt) and not is_completed_on_time:
                        overdue_dt += 1
                            
            completion_rate_val = int((completed_dt / total_dt) * 100) if total_dt > 0 else 0
            overdue_assignments_val = overdue_dt
            
            compliance_modules = {mod for mod, cats in module_categories_map.items() if "Compliance" in cats}
            comp_trackers = [t for t in trackers_dt if t.module in compliance_modules]
            comp_total = len(comp_trackers)
            comp_completed = len([t for t in comp_trackers if t.status == "Completed" and (not t.completed_on or getdate(t.completed_on) <= getdate(dt))])
            compliance_completion_val = int((comp_completed / comp_total) * 100) if comp_total > 0 else 0
            
            return active_learners_val, completion_rate_val, overdue_assignments_val, compliance_completion_val

        for dt in intervals:
            if getdate(dt) > getdate(now()):
                active_learners_history.append(0)
                completion_rate_history.append(0)
                overdue_assignments_history.append(0)
                compliance_completion_history.append(0)
            else:
                a, c, o, cc = compute_metrics_for_date(dt)
                active_learners_history.append(a)
                completion_rate_history.append(c)
                overdue_assignments_history.append(o)
                compliance_completion_history.append(cc)
            
        dt_current = getdate(now())
        active_learners, completion_rate, overdue_assignments, compliance_completion = compute_metrics_for_date(dt_current)
        
        trend_label = "last month" if timeframe == "month" else "last year"
        dt_prev = add_months(dt_current, -1) if timeframe == "month" else add_months(dt_current, -12)
        a_prev, c_prev, o_prev, cc_prev = compute_metrics_for_date(dt_prev)
        
        if a_prev == 0:
            a_pct = 100 if active_learners > 0 else 0
        else:
            a_pct = round(((active_learners - a_prev) / a_prev) * 100)
        a_trend = f"+{a_pct}% {trend_label}" if a_pct >= 0 else f"{a_pct}% {trend_label}"
        
        c_trend = f"vs {c_prev}% {trend_label}"
        
        if o_prev == 0:
            o_pct = 100 if overdue_assignments > 0 else 0
        else:
            o_pct = round(((overdue_assignments - o_prev) / o_prev) * 100)
        o_trend = f"+{o_pct}% {trend_label}" if o_pct >= 0 else f"{o_pct}% {trend_label}"
        
        if cc_prev == 0:
            cc_pct = 100 if compliance_completion > 0 else 0
        else:
            cc_pct = round(((compliance_completion - cc_prev) / cc_prev) * 100)
        cc_trend = f"+{cc_pct}% {trend_label}" if cc_pct >= 0 else f"{cc_pct}% {trend_label}"
        
        return {
            "labels": [getdate(dt).strftime("%b") if timeframe == "year" else f"Week {i+1}" for i, dt in enumerate(intervals)],
            "activeLearners": active_learners,
            "activeLearnersTrend": a_trend,
            "activeLearnersHistory": active_learners_history,
            "completionRate": completion_rate,
            "completionRateTrend": c_trend,
            "completionRateHistory": completion_rate_history,
            "overdueAssignments": overdue_assignments,
            "overdueAssignmentsTrend": o_trend,
            "overdueAssignmentsHistory": overdue_assignments_history,
            "complianceCompletion": compliance_completion,
            "complianceCompletionTrend": cc_trend,
            "complianceCompletionHistory": compliance_completion_history
        }

    return {
        "month": get_data("month"),
        "year": get_data("year")
    }

@frappe.whitelist(allow_guest=True)
def get_learning_content_summary():
    user_filter = _get_filter_for_user()
    if user_filter == []:
        return {"items": [], "total": 0}
        
    # Get all eligible learners based on scope
    learner_filters = {"role": "LMS-Learner"}
    if user_filter is not None:
        learner_filters["parent"] = ["in", user_filter]
        
    all_learner_roles = frappe.get_all("Has Role", filters=learner_filters, fields=["parent"])
    eligible_learners = list(set([r.parent for r in all_learner_roles]))
    total_learners = len(eligible_learners)

    if not eligible_learners:
        return {"items": [], "total": 0}
        
    # Get trackers for eligible learners
    trackers = frappe.get_all("LMS Module Tracker", filters={"user": ["in", eligible_learners]}, fields=["name", "status", "module", "started_on", "creation", "user"])
    
    assignments = frappe.get_all("LMS Module Assignment", fields=["module", "duration"])
    assignment_map = {a.module: a for a in assignments}
    
    trackers_by_user = {u: [] for u in eligible_learners}
    for t in trackers:
        if t.user in trackers_by_user:
            trackers_by_user[t.user].append(t)
            
    status_counts = {
        "Passed": 0,
        "Failed": 0,
        "Overdue": 0,
        "In Progress": 0,
        "Not Started": 0
    }
    
    today_dt = getdate(today())
    
    for user, user_trackers in trackers_by_user.items():
        if not user_trackers:
            status_counts["Not Started"] += 1
            continue
            
        has_failed = False
        has_overdue = False
        has_in_progress = False
        all_passed = True
        
        for t in user_trackers:
            if t.status == "Failed":
                has_failed = True
                all_passed = False
            elif t.status == "Completed":
                score = frappe.db.get_value("LMS Quiz Submission", {"user": t.user, "enrollment": t.name}, "score")
                passing_score = frappe.db.get_value("LMS Module", t.module, "certificate_passing_percentage") or 60
                if score is not None and score < passing_score:
                    has_failed = True
                    all_passed = False
            else:
                all_passed = False
                is_overdue = False
                if t.started_on:
                    a = assignment_map.get(t.module)
                    if a and a.duration:
                        due = add_days(getdate(t.started_on), a.duration)
                        if getdate(due) < today_dt:
                            is_overdue = True

                if is_overdue:
                    has_overdue = True
                elif t.status == "In Progress":
                    has_in_progress = True
                    
        # Hierarchy of statuses: Overdue > Failed > In Progress > Not Started > Passed
        if has_overdue:
            status_counts["Overdue"] += 1
        elif has_failed:
            status_counts["Failed"] += 1
        elif has_in_progress:
            status_counts["In Progress"] += 1
        elif all_passed:
            status_counts["Passed"] += 1
        else:
            status_counts["Not Started"] += 1
            
    results = [{"name": k, "value": v} for k, v in status_counts.items()]
        
    return {
        "items": results,
        "total": total_learners,
    }

@frappe.whitelist(allow_guest=True)
def get_assessment_performance():
    user_filter = _get_filter_for_user()
    if user_filter == []:
        return {"averageScore": 0, "passRate": 0, "needsRetake": 0, "totalAttempts": 0, "retakeRate": 0, "monthlyAttempts": []}
        
    filters = {}
    if user_filter is not None:
        filters["user"] = ["in", user_filter]
        
    trackers = frappe.get_all("LMS Module Tracker", filters=filters, fields=["status", "total_score", "creation", "user", "module"])
    
    completed_trackers = [t for t in trackers if t.status == "Completed"]
    failed_trackers = [t for t in trackers if t.status == "Failed"]
    
    total_completed = len(completed_trackers)
    total_failed = len(failed_trackers)
    
    avg_score = 0
    if total_completed > 0:
        avg_score = sum([t.total_score for t in completed_trackers if t.total_score is not None]) / total_completed
        
    total_attempts = total_completed + total_failed
    pass_rate = int((total_completed / total_attempts) * 100) if total_attempts > 0 else 0
    
    user_module_counts = {}
    for t in trackers:
        if t.status in ("Completed", "Failed"):
            key = (t.user, t.module)
            user_module_counts[key] = user_module_counts.get(key, 0) + 1
            
    retakes = sum(1 for count in user_module_counts.values() if count > 1)
    retake_rate = int((retakes / len(user_module_counts)) * 100) if user_module_counts else 0

    current_year = getdate(today()).year
    monthly_attempts = defaultdict(int)
    for t in trackers:
        if t.status in ("Completed", "Failed"):
            t_date = getdate(t.creation)
            if t_date.year == current_year:
                monthly_attempts[t_date.month] += 1
                
    monthly_data = [{"month": calendar.month_abbr[month], "attempts": monthly_attempts[month]} for month in range(1, 13)]

    return {
        "averageScore": int(avg_score),
        "passRate": pass_rate,
        "needsRetake": total_failed,
        "totalAttempts": total_attempts,
        "retakeRate": retake_rate,
        "monthlyAttempts": monthly_data
    }

@frappe.whitelist(allow_guest=True)
def get_department_performance():
    user = frappe.session.user
    roles = frappe.get_roles(user)
    
    if "System Manager" in roles or "LMS Admin" in roles:
        teams = frappe.get_all("LMS Team", fields=["name", "team_name"])
    elif "LMS Manager" in roles:
        # Manager can only see their own teams!
        # First get teams where user is manager
        managed_teams = frappe.get_all("LMS Team Manager", filters={"user": user}, fields=["parent"])
        team_names = [t.parent for t in managed_teams]
        if not team_names:
            return []
        teams = frappe.get_all("LMS Team", filters={"name": ["in", team_names]}, fields=["name", "team_name"])
    else:
        return []
    
    assignments = frappe.get_all("LMS Module Assignment", fields=["module", "duration"])
    assignment_map = {a.module: a for a in assignments}
    today_dt = getdate(today())
    
    results = []
    for t in teams:
        members = frappe.get_all("LMS Team Member", filters={"parent": t.name}, fields=["user"])
        member_emails = [m.user for m in members]
        
        if not member_emails:
            continue
            
        trackers = frappe.get_all("LMS Module Tracker", filters={"user": ["in", member_emails]}, fields=["user", "status", "total_score", "module", "started_on", "creation"])
        total_t = len(trackers)
        completed = len([tr for tr in trackers if tr.status == "Completed"])
        
        overdue_users = set()
        for tr in trackers:
            if tr.status != "Completed" and tr.started_on:
                a = assignment_map.get(tr.module)
                if a and a.duration:
                    due = getdate(add_days(getdate(tr.started_on), a.duration))
                    if due < today_dt:
                        overdue_users.add(tr.user)
        
        c_rate = int((completed / total_t) * 100) if total_t > 0 else 0
        
        completed_trackers = [tr for tr in trackers if tr.status == "Completed" and tr.total_score is not None]
        avg_score = sum([tr.total_score for tr in completed_trackers]) / len(completed_trackers) if len(completed_trackers) > 0 else 0
        
        results.append({
            "name": t.team_name,
            "completionRate": c_rate,
            "avgScore": int(avg_score),
            "overdueLearners": len(overdue_users),
            "criticalOverdue": len(overdue_users) > 5
        })
    return results
