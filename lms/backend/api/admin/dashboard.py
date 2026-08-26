import frappe
import random
from frappe.utils import today, add_days, getdate, add_months, now

@frappe.whitelist(allow_guest=True)
def get_metrics_summary():
    def get_data(timeframe):
        import calendar
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
        
        all_module_categories = frappe.get_all(
            "LMS Module Category",
            fields=["parent", "category"]
        )
        module_categories_map = {}
        for mc in all_module_categories:
            if mc.parent not in module_categories_map:
                module_categories_map[mc.parent] = set()
            module_categories_map[mc.parent].add(mc.category)
        
        all_learner_roles = frappe.get_all("Has Role", filters={"role": "LMS-Learner"}, fields=["parent", "creation"])
        
        def compute_metrics_for_date(dt):
            learners_by_dt = set([r.parent for r in all_learner_roles if getdate(r.creation) <= getdate(dt)])
            thirty_days_before_dt = add_days(dt, -30)
            trackers_dt = frappe.get_all("LMS Module Tracker", filters={"creation": ["<=", dt]}, fields=["status", "modified", "module", "started_on", "creation", "completed_on", "user"])
            
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
    trackers = frappe.get_all("LMS Module Tracker", fields=["status", "module", "started_on", "creation"])
    
    assignments = frappe.get_all("LMS Module Assignment", fields=["module", "duration"])
    assignment_map = {a.module: a for a in assignments}
    
    status_counts = {
        "Passed": 0,
        "Failed": 0,
        "Overdue": 0,
        "In Progress": 0,
        "Not Started": 0
    }
    
    for t in trackers:
        if t.status == "Completed":
            status_counts["Passed"] += 1
        else:
            is_overdue = False
            if t.started_on:
                a = assignment_map.get(t.module)
                if a and a.duration:
                    due = add_days(getdate(t.started_on), a.duration)
                    if getdate(due) < getdate(today()):
                        is_overdue = True

            if is_overdue:
                status_counts["Overdue"] += 1
            elif t.status == "Failed":
                status_counts["Failed"] += 1
            elif t.status == "In Progress":
                status_counts["In Progress"] += 1
            else:
                status_counts["Not Started"] += 1
                
    total = sum(status_counts.values())
    
    results = []
    for k, v in status_counts.items():
        results.append({
            "name": k,
            "value": int((v / total) * 100) if total > 0 else 0
        })
        
    return results

@frappe.whitelist(allow_guest=True)
def get_learning_content_by_completion():
    trackers = frappe.get_all("LMS Module Tracker", fields=["status", "module", "user"])

    counts = {
        "Highest Completion": 0,
        "Lowest Completion":  0,
        "Completed":          0,
        "In Progress":        0,
        "Not Started":        0,
    }

    module_trackers = {}
    for t in trackers:
        module_trackers.setdefault(t.module, []).append(t)

    for module, module_t_list in module_trackers.items():
        total = len(module_t_list)
        if total == 0:
            continue
        completed_count = sum(1 for t in module_t_list if t.status == "Completed")
        rate = (completed_count / total) * 100
        if rate >= 80:
            counts["Highest Completion"] += total
        elif rate < 30:
            counts["Lowest Completion"] += total

    for t in trackers:
        if t.status == "Completed":
            counts["Completed"] += 1
        elif t.status == "In Progress":
            counts["In Progress"] += 1
        else:
            counts["Not Started"] += 1

    total_all = sum(counts.values())
    results = []
    for k, v in counts.items():
        results.append({
            "name": k,
            "value": int((v / total_all) * 100) if total_all > 0 else 0
        })

    return results

@frappe.whitelist(allow_guest=True)
def get_needs_attention_metrics():
    trackers = frappe.get_all("LMS Module Tracker", fields=["status", "total_score", "module", "started_on", "creation"])
    
    assignments = frappe.get_all("LMS Module Assignment", fields=["module", "duration"])
    assignment_map = {a.module: a for a in assignments}
    
    overdue_learning = 0
    low_scores = 0
    
    for t in trackers:
        if t.status == "Failed" and t.total_score is not None and t.total_score < 60:
            low_scores += 1

        if t.status != "Completed" and t.started_on:
            a = assignment_map.get(t.module)
            if a and a.duration:
                due = add_days(getdate(t.started_on), a.duration)
                if getdate(due) < getdate(today()):
                    overdue_learning += 1
                
    thirty_days_ago = add_days(today(), -30)
    current_learners = frappe.get_all("Has Role", filters={"role": "LMS-Learner"}, pluck="parent")
    total_learners = len(current_learners)
    active_users = len(set([t.user for t in frappe.get_all("LMS Module Tracker", fields=["user"], filters={"modified": [">=", thirty_days_ago]})]))
    inactive_learners = max(0, total_learners - active_users)

    return {
        "overdueLearning": overdue_learning,
        "inactiveLearners": inactive_learners,
        "lowAssessmentScores": low_scores
    }

@frappe.whitelist(allow_guest=True)
def get_assessment_performance():
    trackers = frappe.get_all("LMS Module Tracker", fields=["status", "total_score"])
    
    completed_trackers = [t for t in trackers if t.status == "Completed"]
    failed_trackers = [t for t in trackers if t.status == "Failed"]
    
    total_completed = len(completed_trackers)
    total_failed = len(failed_trackers)
    
    avg_score = 0
    if total_completed > 0:
        avg_score = sum([t.total_score for t in completed_trackers if t.total_score is not None]) / total_completed
        
    total_attempts = total_completed + total_failed
    pass_rate = int((total_completed / total_attempts) * 100) if total_attempts > 0 else 0
    
    return {
        "averageScore": int(avg_score),
        "passRate": pass_rate,
        "needsRetake": total_failed
    }

@frappe.whitelist(allow_guest=True)
def get_onboarding_status():
    thirty_days_ago = add_days(today(), -30)
    new_learner_roles = frappe.get_all(
        "Has Role",
        filters={
            "role": "LMS-Learner",
            "creation": [">=", thirty_days_ago]
        },
        pluck="parent"
    )
    new_users = len(new_learner_roles)
    
    if new_users == 0:
        return {
            "title": "Employee Onboarding",
            "description": "No new employees onboarded recently.",
            "metrics": "0 users",
            "buttonText": "View Onboarding",
            "buttonLink": "/onboarding"
        }
    
    return {
        "title": "New Employee Onboarding",
        "description": "Track the onboarding progress of {0} new employees.".format(new_users),
        "metrics": "{0} users".format(new_users),
        "buttonText": "View Onboarding",
        "buttonLink": "/onboarding"
    }

@frappe.whitelist(allow_guest=True)
def get_learning_insights():
    insights = []
    trackers = frappe.get_all("LMS Module Tracker", fields=["name", "status", "user", "module", "creation", "started_on"])
    if not trackers:
        return []
        
    assignments = frappe.get_all("LMS Module Assignment", fields=["module", "duration"])
    assignment_map = {a.module: a for a in assignments}
    
    total_trackers = len(trackers)
    completed_trackers = [t for t in trackers if t.status == "Completed"]
    if total_trackers > 0:
        completion_rate = int((len(completed_trackers) / total_trackers) * 100)
        insights.append({
            "title": "Completion Rate",
            "description": f"**{completion_rate}% of assigned learning** has been **completed** this month.",
            "type": "success"
        })

    teams = frappe.get_all("LMS Team", fields=["name", "team_name"])
    user_team_map = {}
    for t in teams:
        members = frappe.get_all("LMS Team Member", filters={"parent": t.name}, fields=["user"])
        for m in members:
            user_team_map[m.user] = t.team_name
            
    team_overdue_users = {}
    for t in trackers:
        if t.status != "Completed" and t.started_on:
            a = assignment_map.get(t.module)
            if a and a.duration:
                due_date = add_days(getdate(t.started_on), a.duration)
                if getdate(due_date) < getdate(today()):
                    team = user_team_map.get(t.user)
                    if team:
                        if team not in team_overdue_users:
                            team_overdue_users[team] = set()
                        team_overdue_users[team].add(t.user)
                        
    if team_overdue_users:
        worst_team = max(team_overdue_users, key=lambda k: len(team_overdue_users[k]))
        overdue_count = len(team_overdue_users[worst_team])
        if overdue_count > 0:
            insights.append({
                "title": "Overdue Alerts",
                "description": f"**{worst_team} has the highest** number of **overdue learners ({overdue_count})**.",
                "type": "destructive"
            })

    module_completed_counts = {}
    for t in completed_trackers:
        module_completed_counts[t.module] = module_completed_counts.get(t.module, 0) + 1
        
    if module_completed_counts:
        top_module = max(module_completed_counts, key=module_completed_counts.get)
        insights.append({
            "title": "Popular Content",
            "description": f"**{top_module}** is the most **completed module**.",
            "type": "info"
        })

    not_started_users = set([t.user for t in trackers if t.status == "Not started"])
    not_started_count = len(not_started_users)
    if not_started_count > 0:
        insights.append({
            "title": "Engagement Drop",
            "description": f"**{not_started_count} learners** haven't started their **assigned training**.",
            "type": "warning"
        })

    trackers_scores = frappe.get_all("LMS Module Tracker", fields=["status", "creation"], filters={"status": ["in", ["Completed", "Failed"]]})
    
    thirty_days_ago = add_days(today(), -30)
    sixty_days_ago = add_days(today(), -60)
    
    current_month_attempts = [t for t in trackers_scores if getdate(t.creation) >= getdate(thirty_days_ago)]
    prev_month_attempts = [t for t in trackers_scores if getdate(sixty_days_ago) <= getdate(t.creation) < getdate(thirty_days_ago)]
    
    def get_pass_rate(attempt_list):
        if not attempt_list: return 0
        passed = len([t for t in attempt_list if t.status == "Completed"])
        return int((passed / len(attempt_list)) * 100)
        
    current_pass_rate = get_pass_rate(current_month_attempts)
    prev_pass_rate = get_pass_rate(prev_month_attempts)
    
    if current_month_attempts and prev_month_attempts:
        diff = current_pass_rate - prev_pass_rate
        if diff >= 0:
            insights.append({
                "title": "Performance Up",
                "description": f"**Assessment pass rate improved by {diff}%** compared to last month.",
                "type": "success"
            })
        else:
            insights.append({
                "title": "Performance Down",
                "description": f"**Assessment pass rate dropped by {abs(diff)}%** compared to last month.",
                "type": "warning"
            })
    elif current_month_attempts:
        insights.append({
            "title": "Performance",
            "description": f"**Assessment pass rate** is currently at **{current_pass_rate}%**.",
            "type": "success" if current_pass_rate >= 80 else "warning"
        })

    return insights
