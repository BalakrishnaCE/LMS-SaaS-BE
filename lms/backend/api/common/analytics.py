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
        
        quiz_submissions = frappe.get_all("LMS Quiz Submission", fields=["score", "submitted_on", "user"])

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
            
            completed_on_time_dt = 0
            completed_with_due_dt = 0
            attention_users = set()
            
            for t in trackers_dt:
                is_completed_by_dt = (t.status == "Completed" and (not t.completed_on or getdate(t.completed_on) <= getdate(dt)))
                if is_completed_by_dt:
                    completed_dt += 1
                
                if t.status == "Failed" and (not t.modified or getdate(t.modified) <= getdate(dt)):
                    if t.user in learners_by_dt:
                        attention_users.add(t.user)
                
                a = assignment_map.get(t.module)
                if a and a.duration and t.started_on:
                    start_date = getdate(t.started_on)
                    due_date = add_days(start_date, a.duration)
                    if getdate(due_date) < getdate(dt) and not is_completed_by_dt:
                        overdue_dt += 1
                        if t.user in learners_by_dt:
                            attention_users.add(t.user)
                    
                    if is_completed_by_dt:
                        completed_with_due_dt += 1
                        if t.completed_on and getdate(t.completed_on) <= getdate(due_date):
                            completed_on_time_dt += 1
                            
            completion_rate_val = int((completed_dt / total_dt) * 100) if total_dt > 0 else 0
            overdue_assignments_val = overdue_dt
            
            compliance_modules = {mod for mod, cats in module_categories_map.items() if "Compliance" in cats}
            comp_trackers = [t for t in trackers_dt if t.module in compliance_modules]
            comp_total = len(comp_trackers)
            comp_completed = len([t for t in comp_trackers if t.status == "Completed" and (not t.completed_on or getdate(t.completed_on) <= getdate(dt))])
            compliance_completion_val = int((comp_completed / comp_total) * 100) if comp_total > 0 else 0
            
            scores_dt = [s.score for s in quiz_submissions if s.submitted_on and getdate(s.submitted_on) <= getdate(dt) and s.user in learners_by_dt]
            assessment_score_val = int(sum(scores_dt) / len(scores_dt)) if len(scores_dt) > 0 else 0
            on_time_completion_val = int((completed_on_time_dt / completed_with_due_dt) * 100) if completed_with_due_dt > 0 else 0
            learners_needing_attention_val = len(attention_users)
            
            return active_learners_val, completion_rate_val, overdue_assignments_val, compliance_completion_val, assessment_score_val, on_time_completion_val, learners_needing_attention_val

        assessment_score_history = []
        on_time_completion_history = []
        learners_needing_attention_history = []

        for dt in intervals:
            if getdate(dt) > getdate(now()):
                active_learners_history.append(0)
                completion_rate_history.append(0)
                overdue_assignments_history.append(0)
                compliance_completion_history.append(0)
                assessment_score_history.append(0)
                on_time_completion_history.append(0)
                learners_needing_attention_history.append(0)
            else:
                a, c, o, cc, asc, otc, lna = compute_metrics_for_date(dt)
                active_learners_history.append(a)
                completion_rate_history.append(c)
                overdue_assignments_history.append(o)
                compliance_completion_history.append(cc)
                assessment_score_history.append(asc)
                on_time_completion_history.append(otc)
                learners_needing_attention_history.append(lna)
            
        dt_current = getdate(now())
        active_learners, completion_rate, overdue_assignments, compliance_completion, assessment_score, on_time_completion, learners_needing_attention = compute_metrics_for_date(dt_current)
        
        trend_label = "last month" if timeframe == "month" else "last year"
        dt_prev = add_months(dt_current, -1) if timeframe == "month" else add_months(dt_current, -12)
        a_prev, c_prev, o_prev, cc_prev, asc_prev, otc_prev, lna_prev = compute_metrics_for_date(dt_prev)
        
        def calc_trend(current, prev, is_percentage=True):
            if prev == 0:
                pct = 100 if current > 0 else 0
            else:
                pct = round(((current - prev) / prev) * 100)
            prefix = "+" if pct >= 0 else ""
            if is_percentage:
                return f"{prefix}{pct}% {trend_label}"
            else:
                diff = current - prev
                prefix = "+" if diff >= 0 else ""
                return f"{prefix}{diff} {trend_label}"
        
        a_trend = calc_trend(active_learners, a_prev)
        c_trend = f"vs {c_prev}% {trend_label}"
        o_trend = calc_trend(overdue_assignments, o_prev)
        cc_trend = calc_trend(compliance_completion, cc_prev)
        asc_trend = f"vs {asc_prev}% {trend_label}"
        otc_trend = f"vs {otc_prev}% {trend_label}"
        lna_trend = calc_trend(learners_needing_attention, lna_prev, is_percentage=False)
        
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
            "complianceCompletionHistory": compliance_completion_history,
            "assessmentScore": assessment_score,
            "assessmentScoreTrend": asc_trend,
            "assessmentScoreHistory": assessment_score_history,
            "onTimeCompletion": on_time_completion,
            "onTimeCompletionTrend": otc_trend,
            "onTimeCompletionHistory": on_time_completion_history,
            "learnersNeedingAttention": learners_needing_attention,
            "learnersNeedingAttentionTrend": lna_trend,
            "learnersNeedingAttentionHistory": learners_needing_attention_history
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

@frappe.whitelist(allow_guest=True)
def get_recently_assigned_learning():
    user_filter = _get_filter_for_user()
    if user_filter == []:
        return []
        
    learner_filters = {"role": "LMS-Learner"}
    if user_filter is not None:
        learner_filters["parent"] = ["in", user_filter]
        
    all_learner_roles = frappe.get_all("Has Role", filters=learner_filters, fields=["parent"])
    eligible_learners = list(set([r.parent for r in all_learner_roles]))
    
    if not eligible_learners:
        return []

    # Get recent activity/assignments from trackers
    recent_trackers = frappe.get_all(
        "LMS Module Tracker",
        filters={"user": ["in", eligible_learners]},
        fields=["module", "creation"],
        order_by="creation desc",
        limit=100
    )
    
    recent_modules = []
    seen = set()
    for t in recent_trackers:
        if t.module not in seen:
            seen.add(t.module)
            recent_modules.append(t.module)
            if len(recent_modules) >= 5:
                break
                
    if not recent_modules:
        return []
        
    results = []
    
    modules = frappe.get_all(
        "LMS Module",
        filters={"name": ["in", recent_modules]},
        fields=["name", "module_name"]
    )
    module_map = {m.name: m.module_name for m in modules}
    
    all_module_categories = frappe.get_all("LMS Module Category", fields=["parent", "category"])
    module_categories_map = {}
    for mc in all_module_categories:
        if mc.parent not in module_categories_map:
            module_categories_map[mc.parent] = set()
        module_categories_map[mc.parent].add(mc.category)
        
    trackers = frappe.get_all(
        "LMS Module Tracker",
        filters={
            "module": ["in", recent_modules],
            "user": ["in", eligible_learners]
        },
        fields=["module", "status", "user"]
    )
    
    for mod in recent_modules:
        mod_trackers = [t for t in trackers if t.module == mod]
        
        assigned = len(mod_trackers)
        # Skip modules that have 0 assigned learners in this scope
        if assigned == 0:
            continue
            
        in_progress = len([t for t in mod_trackers if t.status == "In Progress"])
        completed = len([t for t in mod_trackers if t.status == "Completed"])
        
        c_rate = int((completed / assigned) * 100) if assigned > 0 else 0
        
        cats = list(module_categories_map.get(mod, []))
        cat_str = cats[0] if cats else "General"
        
        results.append({
            "id": mod,
            "name": module_map.get(mod, mod),
            "type": "Module",
            "category": cat_str,
            "assignedLearners": assigned,
            "inProgress": in_progress,
            "completed": completed,
            "completionRate": c_rate
        })
        
    return results

@frappe.whitelist(allow_guest=True)
def get_module_details_analytics(module_id):
    user_filter = _get_filter_for_user()
    if user_filter == []:
        return {}
        
    learner_filters = {"role": "LMS-Learner"}
    if user_filter is not None:
        learner_filters["parent"] = ["in", user_filter]
        
    all_learner_roles = frappe.get_all("Has Role", filters=learner_filters, fields=["parent"])
    eligible_learners = list(set([r.parent for r in all_learner_roles]))
    
    if not eligible_learners:
        return {}

    # Get module details
    try:
        mod_doc = frappe.get_doc("LMS Module", module_id)
    except frappe.DoesNotExistError:
        return {}
        
    category_docs = frappe.get_all("LMS Module Category", filters={"parent": module_id}, fields=["category"])
    cat_str = category_docs[0].category if category_docs else "General"

    # Get trackers for eligible learners
    trackers = frappe.get_all(
        "LMS Module Tracker",
        filters={
            "module": module_id,
            "user": ["in", eligible_learners]
        },
        fields=["name", "user", "status", "progress_percentage", "creation"]
    )
    
    total_learners = len(trackers)
    if total_learners == 0:
        return {
            "moduleName": mod_doc.module_name,
            "category": cat_str,
            "type": "Module",
            "overview": {"totalLearners": 0, "pass": 0, "inProgress": 0, "notStarted": 0, "overdue": 0},
            "departmentBreakdown": [],
            "topLearners": []
        }
        
    # User info and teams
    users = frappe.get_all("User", filters={"name": ["in", [t.user for t in trackers]]}, fields=["name", "full_name", "email"])
    user_map = {u.name: u for u in users}
    
    team_members = frappe.get_all("LMS Team Member", filters={"user": ["in", [t.user for t in trackers]]}, fields=["user", "parent"])
    user_team_map = {}
    for tm in team_members:
        if tm.user not in user_team_map:
            user_team_map[tm.user] = []
        user_team_map[tm.user].append(tm.parent)
        
    teams = frappe.get_all("LMS Team", fields=["name", "team_name"])
    team_name_map = {t.name: t.team_name for t in teams}

    passed = 0
    in_progress = 0
    not_started = 0
    overdue = 0
    
    duration = mod_doc.duration or 0
    now_ts = frappe.utils.now_datetime()
    
    dept_data = {}
    top_learners = []
    
    for t in trackers:
        # Check overdue
        is_overdue = False
        if duration > 0 and t.status != "Completed":
            created_dt = frappe.utils.get_datetime(t.creation)
            due_dt = frappe.utils.add_days(created_dt, duration)
            if due_dt < now_ts:
                is_overdue = True
                
        if t.status == "Completed":
            passed += 1
        elif is_overdue:
            overdue += 1
        elif t.status == "In Progress":
            in_progress += 1
        else:
            not_started += 1
            
        u_info = user_map.get(t.user)
        u_teams = user_team_map.get(t.user, [])
        primary_team_id = u_teams[0] if u_teams else None
        primary_team_name = team_name_map.get(primary_team_id, "No Department")
        
        # Dept breakdown
        if primary_team_name not in dept_data:
            dept_data[primary_team_name] = {"assigned": 0, "completed": 0}
        dept_data[primary_team_name]["assigned"] += 1
        if t.status == "Completed":
            dept_data[primary_team_name]["completed"] += 1
            
        # Top learners
        top_learners.append({
            "name": u_info.full_name if u_info else t.user,
            "email": u_info.email if u_info else t.user,
            "department": primary_team_name,
            "status": "Completed" if t.status == "Completed" else "In Progress" if t.status == "In Progress" else "Not Started",
            "completionRate": int(t.progress_percentage or 0)
        })
        
    dept_breakdown = []
    for dept, data in dept_data.items():
        c_rate = int((data["completed"] / data["assigned"]) * 100) if data["assigned"] > 0 else 0
        dept_breakdown.append({
            "department": dept,
            "assigned": data["assigned"],
            "completed": data["completed"],
            "completionRate": c_rate
        })
        
    top_learners = sorted(top_learners, key=lambda x: x["completionRate"], reverse=True)[:50]

    return {
        "moduleName": mod_doc.module_name,
        "category": cat_str,
        "type": "Module",
        "overview": {
            "totalLearners": total_learners,
            "pass": int((passed / total_learners) * 100),
            "inProgress": int((in_progress / total_learners) * 100),
            "notStarted": int((not_started / total_learners) * 100),
            "overdue": int((overdue / total_learners) * 100)
        },
        "departmentBreakdown": dept_breakdown,
        "topLearners": top_learners
    }

@frappe.whitelist(allow_guest=True)
def get_assessment_performance_list(assessment_type="all"):
    user_filter = _get_filter_for_user()
    if user_filter == []:
        return []
        
    filters = {}
    if user_filter is not None:
        filters["user"] = ["in", user_filter]

    # QA Assessments not supported in backend yet
    if assessment_type == "qa":
        return []

    submissions = frappe.get_all("LMS Quiz Submission", filters=filters, fields=["name", "user", "quiz", "score", "passed", "creation", "enrollment"], ignore_permissions=True)
    
    if not submissions:
        return []
        
    quiz_names = list(set([s.quiz for s in submissions]))
    quizzes = frappe.get_all("LMS Quiz", filters={"name": ["in", quiz_names]}, fields=["name", "title", "total_score", "passing_percentage", "max_attempts"], ignore_permissions=True)
    quiz_map = {q.name: q for q in quizzes}
    
    tracker_names = list(set([s.enrollment for s in submissions if s.enrollment]))
    trackers = frappe.get_all("LMS Module Tracker", filters={"name": ["in", tracker_names]}, fields=["name", "module"], ignore_permissions=True)
    tracker_map = {t.name: t.module for t in trackers}
    
    module_names = list(set([t.module for t in trackers]))
    modules = frappe.get_all("LMS Module", filters={"name": ["in", module_names]}, fields=["name", "module_name"], ignore_permissions=True)
    module_map = {m.name: m.module_name for m in modules}
    
    users = frappe.get_all("User", filters={"name": ["in", [s.user for s in submissions]]}, fields=["name", "full_name", "email"], ignore_permissions=True)
    user_map = {u.name: u for u in users}

    user_quiz_attempts = {}
    for s in submissions:
        key = (s.user, s.quiz)
        user_quiz_attempts[key] = user_quiz_attempts.get(key, 0) + 1

    submissions.sort(key=lambda x: frappe.utils.get_datetime(x.creation), reverse=True)
    latest_submissions = {}
    for s in submissions:
        key = (s.user, s.quiz)
        if key not in latest_submissions:
            latest_submissions[key] = s
            
    results = []
    for (user, quiz_id), s in latest_submissions.items():
        q_doc = quiz_map.get(quiz_id)
        if not q_doc:
            continue
            
        u_info = user_map.get(user)
        mod_name = module_map.get(tracker_map.get(s.enrollment)) if s.enrollment else "Unknown Module"
        
        attempts_used = user_quiz_attempts.get((user, quiz_id), 1)
        max_attempts = q_doc.max_attempts or 0
        attempts_str = f"{attempts_used}/{max_attempts} used" if max_attempts > 0 else f"{attempts_used} used"
        
        results.append({
            "submissionId": s.name,
            "learnerName": u_info.full_name if u_info else user,
            "learnerEmail": u_info.email if u_info else user,
            "assessmentName": q_doc.title or quiz_id,
            "moduleName": mod_name,
            "type": "QUIZ",
            "score": f"{int(s.score or 0)}/{int(q_doc.total_score or 100)}",
            "passScore": int(q_doc.passing_percentage or 0),
            "attempts": attempts_str,
            "status": "Pass" if s.passed else "Failed"
        })
        
    return results

@frappe.whitelist(allow_guest=True)
def get_assessment_details(submission_id):
    user_filter = _get_filter_for_user()
    if user_filter == []:
        return None

    submissions = frappe.get_all("LMS Quiz Submission", filters={"name": submission_id}, fields=["name", "user", "quiz", "score", "passed", "time_taken", "submitted_on", "evaluation_feedback", "enrollment"], ignore_permissions=True)
    if not submissions:
        return None
    sub = submissions[0]

    if user_filter is not None and sub.user not in user_filter:
        return None

    users = frappe.get_all("User", filters={"name": sub.user}, fields=["full_name", "email"], ignore_permissions=True)
    u_info = users[0] if users else None

    team_members = frappe.get_all("LMS Team Member", filters={"user": sub.user}, fields=["parent"])
    department = "No Department"
    if team_members:
        teams = frappe.get_all("LMS Team", filters={"name": team_members[0].parent}, fields=["team_name"])
        if teams:
            department = teams[0].team_name

    quizzes = frappe.get_all("LMS Quiz", filters={"name": sub.quiz}, fields=["title", "total_score", "time_limit_mins", "passing_percentage"], ignore_permissions=True)
    quiz = quizzes[0] if quizzes else None

    module_name = ""
    if sub.enrollment:
        trackers = frappe.get_all("LMS Module Tracker", filters={"name": sub.enrollment}, fields=["module"], ignore_permissions=True)
        if trackers:
            modules = frappe.get_all("LMS Module", filters={"name": trackers[0].module}, fields=["module_name"], ignore_permissions=True)
            if modules:
                module_name = modules[0].module_name

    responses = frappe.get_all("LMS Quiz Response", filters={"parent": submission_id}, fields=["question", "selected_option", "is_correct", "evaluation_data", "manual_score"], ignore_permissions=True)
    
    question_ids = [r.question for r in responses if r.question]
    q_map = {}
    if question_ids:
        questions = frappe.get_all("LMS Quiz Question", filters={"name": ["in", question_ids]}, fields=["name", "question_text", "score"], ignore_permissions=True)
        q_map = {q.name: q for q in questions}

    correct_options = {}
    if question_ids:
        options = frappe.get_all("LMS Quiz Option", filters={"parent": ["in", question_ids]}, fields=["parent", "option_text", "is_correct"], ignore_permissions=True)
        for opt in options:
            if opt.is_correct:
                correct_options[opt.parent] = opt.option_text
            
    responses_data = []
    correct_count = 0
    incorrect_count = 0

    for r in responses:
        q_info = q_map.get(r.question)
        if not q_info:
            continue
            
        if r.is_correct:
            correct_count += 1
        else:
            incorrect_count += 1
            
        import json
        feedback_str = ""
        if r.evaluation_data:
            try:
                eval_data = json.loads(r.evaluation_data)
                if isinstance(eval_data, dict):
                    feedback_str = eval_data.get("feedback", "")
            except:
                feedback_str = str(r.evaluation_data)

        responses_data.append({
            "questionText": frappe.utils.strip_html(q_info.question_text) if q_info.question_text else "",
            "learnerAnswer": r.selected_option or "No Answer",
            "isCorrect": bool(r.is_correct),
            "correctAnswer": correct_options.get(r.question, ""),
            "score": r.manual_score if r.manual_score is not None else (q_info.score if r.is_correct else 0),
            "maxScore": q_info.score or 0,
            "feedback": feedback_str
        })

    time_taken_sec = int(sub.time_taken or 0)
    mins, secs = divmod(time_taken_sec, 60)
    time_taken_str = f"{mins} min {secs:02d} sec"
    if quiz and quiz.time_limit_mins:
        time_taken_str += f" / {quiz.time_limit_mins} mins"

    overall_score = 0
    if quiz and quiz.total_score:
        overall_score = int(((sub.score or 0) / quiz.total_score) * 100)

    taken_on = frappe.utils.formatdate(sub.submitted_on, "MMM dd, yyyy") if sub.submitted_on else ""

    return {
        "assessmentTitle": quiz.title if quiz else sub.quiz,
        "moduleName": module_name,
        "learner": {
            "name": u_info.full_name if u_info else sub.user,
            "email": u_info.email if u_info else sub.user,
            "designation": u_info.get("designation", "") if u_info else "",
            "department": department
        },
        "takenOn": f"Taken On: {taken_on}" if taken_on else "",
        "overallScore": f"{overall_score}%",
        "passed": bool(sub.passed),
        "completedPoints": f"{int(sub.score or 0)} / {int(quiz.total_score if quiz else 0)}",
        "timeTaken": time_taken_str,
        "overallFeedback": sub.evaluation_feedback or "",
        "summary": f"{correct_count} correct · {incorrect_count} incorrect",
        "responses": responses_data
    }

@frappe.whitelist(allow_guest=True)
def debug_all_submissions():
    return frappe.get_all("LMS Quiz Submission", fields=["name", "quiz", "score", "time_taken"], limit=5, order_by="creation desc", ignore_permissions=True)

@frappe.whitelist(allow_guest=True)
def debug_submission(sub_id):
    sub = frappe.get_all("LMS Quiz Submission", filters={"name": sub_id}, fields=["*"], ignore_permissions=True)
    resp = frappe.get_all("LMS Quiz Response", filters={"parent": sub_id}, fields=["*"], ignore_permissions=True)
    return {"submission": sub, "responses": resp}
