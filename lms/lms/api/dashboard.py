import frappe
import random
from frappe.utils import today, add_days, getdate, add_months, now

@frappe.whitelist(allow_guest=True)
def get_metrics_summary():
    # Define the 6 historical snapshots (months ago)
    intervals = [add_months(now(), -i) for i in range(5, -1, -1)]
    
    active_learners_history = []
    completion_rate_history = []
    overdue_assignments_history = []
    compliance_completion_history = []
    
    # Pre-fetch assignment lookup map
    assignments = frappe.get_all("LMS Module Assignment", fields=["name", "module", "duration", "creation", "is_mandatory"])
    assignment_map = {a.module: a for a in assignments}
    
    # Get all users who have the LMS-Learner role
    learners = frappe.get_all("Has Role", filters={"role": "LMS-Learner"}, pluck="parent")
    if not learners:
        learners = ["no_learners_found"] # Prevent empty IN clause SQL error
        
    for dt in intervals:
        # Active Learners up to this date, only counting users with LMS-Learner role
        active_learners_history.append(frappe.db.count("User", {
            "creation": ["<=", dt],
            "name": ["in", learners]
        }))
        
        # Trackers up to this date
        trackers_dt = frappe.get_all("LMS Module Tracker", filters={"creation": ["<=", dt]}, fields=["status", "modified", "module", "started_on", "creation", "completed_on"])
        total_dt = len(trackers_dt)
        
        completed_dt = 0
        overdue_dt = 0
        
        for t in trackers_dt:
            is_completed_by_dt = (t.status == "Completed" and t.completed_on and getdate(t.completed_on) <= getdate(dt))
            if is_completed_by_dt:
                completed_dt += 1
            
            # Check if overdue at this snapshot
            a = assignment_map.get(t.module)
            if a and a.duration:
                start_date = getdate(t.started_on) if t.started_on else getdate(t.creation)
                if start_date <= getdate(dt):
                    due_date = add_days(start_date, a.duration)
                    is_finished_by_dt = (t.status in ["Completed", "Failed"] and ((t.completed_on and getdate(t.completed_on) <= getdate(dt)) or getdate(t.creation) <= getdate(dt)))
                    # Fallback to creation for Failed since Failed might not have completed_on in seed
                    if getdate(due_date) < getdate(dt) and not is_finished_by_dt:
                        overdue_dt += 1
                        
        completion_rate_history.append(int((completed_dt / total_dt) * 100) if total_dt > 0 else 0)
        overdue_assignments_history.append(overdue_dt)
        
        # Compliance completion (mandatory modules)
        mandatory_modules = [m for m, a in assignment_map.items() if a.is_mandatory]
        comp_trackers = [t for t in trackers_dt if t.module in mandatory_modules]
        comp_total = len(comp_trackers)
        comp_completed = len([t for t in comp_trackers if t.status == "Completed" and t.completed_on and getdate(t.completed_on) <= getdate(dt)])
        compliance_completion_history.append(int((comp_completed / comp_total) * 100) if comp_total > 0 else 0)
        
    # Current values are simply the most recent snapshot
    active_learners = active_learners_history[-1]
    completion_rate = completion_rate_history[-1]
    overdue_assignments = overdue_assignments_history[-1]
    compliance_completion = compliance_completion_history[-1]
    
    # Calculate specific trend strings matching original UI
    a_prev = active_learners_history[-2] if len(active_learners_history) > 1 else active_learners
    a_pct = int(((active_learners - a_prev) / a_prev) * 100) if a_prev > 0 else 0
    a_trend = f"+{a_pct}% this month" if a_pct >= 0 else f"{a_pct}% this month"
    
    c_prev = completion_rate_history[-2] if len(completion_rate_history) > 1 else completion_rate
    c_trend = f"vs {c_prev}% last month"
    
    o_prev = overdue_assignments_history[-2] if len(overdue_assignments_history) > 1 else overdue_assignments
    o_pct = int(((overdue_assignments - o_prev) / o_prev) * 100) if o_prev > 0 else 0
    o_trend = f"+{o_pct}% this month" if o_pct >= 0 else f"{o_pct}% this month"
    
    cc_prev = compliance_completion_history[-2] if len(compliance_completion_history) > 1 else compliance_completion
    cc_diff = compliance_completion - cc_prev
    cc_trend = f"+{cc_diff}% this month" if cc_diff >= 0 else f"{cc_diff}% this month"
    
    return {
        "activeLearners": active_learners,
        "activeLearnersTrend": a_trend if a_pct != 0 else "Trending steady",
        "activeLearnersHistory": active_learners_history,
        
        "completionRate": completion_rate,
        "completionRateTrend": c_trend,
        "completionRateHistory": completion_rate_history,
        
        "overdueAssignments": overdue_assignments,
        "overdueAssignmentsTrend": o_trend if o_pct != 0 else "Needs review",
        "overdueAssignmentsHistory": overdue_assignments_history,
        
        "complianceCompletion": compliance_completion,
        "complianceCompletionTrend": cc_trend if cc_diff != 0 else "On track",
        "complianceCompletionHistory": compliance_completion_history
    }

@frappe.whitelist(allow_guest=True)
def get_department_performance():
    teams = frappe.get_all("LMS Team", fields=["name", "team_name"])
    
    assignments = frappe.get_all("LMS Module Assignment", fields=["module", "duration"])
    assignment_map = {a.module: a for a in assignments}
    today_dt = getdate(today())
    
    results = []
    for t in teams:
        # Get members of this team
        members = frappe.get_all("LMS Team Member", filters={"parent": t.name}, fields=["user"])
        member_emails = [m.user for m in members]
        
        if not member_emails:
            continue
            
        trackers = frappe.get_all("LMS Module Tracker", filters={"user": ["in", member_emails]}, fields=["user", "status", "total_score", "module", "started_on", "creation"])
        total_t = len(trackers)
        completed = len([tr for tr in trackers if tr.status == "Completed"])
        
        overdue_users = set()
        for tr in trackers:
            if tr.status in ["In Progress", "Not started"]:
                a = assignment_map.get(tr.module)
                if a and a.duration:
                    start_date = getdate(tr.started_on) if tr.started_on else getdate(tr.creation)
                    due = getdate(add_days(start_date, a.duration))
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
def get_upcoming_deadlines():
    assignments = frappe.get_all("LMS Module Assignment", fields=["name", "module", "duration", "is_mandatory"])
    assignment_map = {a.module: a for a in assignments}
    
    # We want to find which modules have the most learners approaching their deadline within 30 days
    approaching = {}
    today_dt = getdate(today())
    next_week = getdate(add_days(today_dt, 30))
    
    trackers = frappe.get_all("LMS Module Tracker", filters={"status": ["in", ["In Progress", "Not started"]]}, fields=["module", "started_on", "creation"])
    for t in trackers:
        a = assignment_map.get(t.module)
        if a and a.duration:
            start_date = getdate(t.started_on) if t.started_on else getdate(t.creation)
            due = getdate(add_days(start_date, a.duration))
            if today_dt <= due <= next_week:
                if t.module not in approaching:
                    approaching[t.module] = {"count": 0, "mandatory": a.is_mandatory}
                approaching[t.module]["count"] += 1
                
    results = []
    for module_name, data in approaching.items():
        results.append({
            "id": module_name,
            "name": module_name, # Since module is a Link, the ID is the module name
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
        # Count trackers for this module
        trackers = frappe.get_all("LMS Module Tracker", filters={"module": a.module}, fields=["status"])
        total_assigned = len(trackers)
        completed = len([t for t in trackers if t.status == "Completed"])
        progress = int((completed / total_assigned) * 100) if total_assigned > 0 else 0
        
        results.append({
            "id": a.name,
            "name": a.module, # using module as name since title is gone
            "assignedLearners": total_assigned,
            "dueDate": f"{a.duration} Days" if a.duration else "No Limit",
            "progress": progress,
            "actions": ["View Progress", "Send Reminder"]
        })
    return results

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
        elif t.status == "Failed":
            status_counts["Failed"] += 1
        else:
            is_overdue = False
            a = assignment_map.get(t.module)
            if a and a.duration:
                start_date = getdate(t.started_on) if t.started_on else getdate(t.creation)
                due = add_days(start_date, a.duration)
                if getdate(due) < getdate(today()):
                    is_overdue = True
                    
            if is_overdue:
                status_counts["Overdue"] += 1
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
def get_needs_attention_metrics():
    trackers = frappe.get_all("LMS Module Tracker", fields=["status", "total_score", "module", "started_on", "creation"])
    
    assignments = frappe.get_all("LMS Module Assignment", fields=["module", "duration"])
    assignment_map = {a.module: a for a in assignments}
    
    overdue_learning = 0
    low_scores = 0
    
    for t in trackers:
        if t.status == "Failed" and t.total_score is not None and t.total_score < 60:
            low_scores += 1
            
        if t.status in ["In Progress", "Not started"]:
            a = assignment_map.get(t.module)
            if a and a.duration:
                start_date = getdate(t.started_on) if t.started_on else getdate(t.creation)
                due = add_days(start_date, a.duration)
                if getdate(due) < getdate(today()):
                    overdue_learning += 1
                
    # Inactive Learners (simulated by checking users with no trackers)
    learners = frappe.get_all("Has Role", filters={"role": "LMS-Learner"}, pluck="parent")
    if not learners:
        learners = ["no_learners_found"]
        
    total_learners = frappe.db.count("User", {"name": ["in", learners]})
    active_users = len(set([t.user for t in frappe.get_all("LMS Module Tracker", fields=["user"])]))
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
    
    learners = frappe.get_all("Has Role", filters={"role": "LMS-Learner"}, pluck="parent")
    if not learners:
        learners = ["no_learners_found"]
        
    new_users = frappe.db.count("User", {
        "creation": [">=", thirty_days_ago],
        "name": ["in", learners]
    })
    
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
        "description": f"Track the onboarding progress of {new_users} new employees.",
        "metrics": f"{new_users} users",
        "buttonText": "View Onboarding",
        "buttonLink": "/onboarding"
    }

@frappe.whitelist(allow_guest=True)
def get_learning_insights():
    teams = frappe.get_all("LMS Team", fields=["name", "team_name"])
    if not teams:
        return []
        
    team_scores = {}
    team_in_progress = {}
    
    for t in teams:
        members = frappe.get_all("LMS Team Member", filters={"parent": t.name}, fields=["user"])
        member_emails = [m.user for m in members]
        if not member_emails:
            continue
            
        trackers = frappe.get_all("LMS Module Tracker", filters={"user": ["in", member_emails]}, fields=["status", "total_score"])
        
        completed = [tr for tr in trackers if tr.status == "Completed" and tr.total_score is not None]
        if completed:
            avg_score = sum([tr.total_score for tr in completed]) / len(completed)
            team_scores[t.team_name] = avg_score
            
        in_progress = len([tr for tr in trackers if tr.status == "In Progress"])
        team_in_progress[t.team_name] = in_progress

    insights = []
    if team_scores:
        top_team = max(team_scores, key=team_scores.get)
        bottom_team = min(team_scores, key=team_scores.get)
        
        insights.append({
            "title": "Top Performing Department",
            "description": f"{top_team} leads with the highest average assessment score of {int(team_scores[top_team])}%.",
            "type": "success"
        })
        if top_team != bottom_team:
            insights.append({
                "title": "Needs Support",
                "description": f"{bottom_team} has the lowest average assessment score ({int(team_scores[bottom_team])}%). Consider providing additional resources.",
                "type": "warning"
            })
            
    if team_in_progress:
        top_learning_team = max(team_in_progress, key=team_in_progress.get)
        if team_in_progress[top_learning_team] > 0:
            insights.append({
                "title": "High Engagement",
                "description": f"{top_learning_team} currently has {team_in_progress[top_learning_team]} active learners in progress. Great momentum!",
                "type": "info"
            })
            
    return insights
