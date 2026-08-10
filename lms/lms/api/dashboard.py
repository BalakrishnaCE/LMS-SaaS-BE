import frappe
import random
from frappe.utils import today, add_days, getdate, add_months

@frappe.whitelist(allow_guest=True)
def get_metrics_summary():
    # Define the 6 historical snapshots (months ago)
    intervals = [add_months(today(), -i) for i in range(5, -1, -1)]
    
    active_learners_history = []
    completion_rate_history = []
    overdue_assignments_history = []
    
    # Pre-fetch assignment lookup map
    assignments = frappe.get_all("LMS Module Assignment", fields=["name", "due_date", "creation"])
    assignment_map = {a.name: a for a in assignments}
    
    for dt in intervals:
        # Active Learners up to this date
        active_learners_history.append(frappe.db.count("User", {"creation": ["<=", dt]}))
        
        # Trackers up to this date
        trackers_dt = frappe.get_all("LMS Module Tracker", filters={"creation": ["<=", dt]}, fields=["status", "modified", "assignment"])
        total_dt = len(trackers_dt)
        
        completed_dt = 0
        overdue_dt = 0
        
        for t in trackers_dt:
            is_completed_by_dt = (t.status == "Completed" and getdate(t.modified) <= getdate(dt))
            if is_completed_by_dt:
                completed_dt += 1
            
            # Check if overdue at this snapshot
            if t.assignment and t.assignment in assignment_map:
                a = assignment_map[t.assignment]
                # If assignment due_date is before the snapshot date, and it wasn't completed by the snapshot
                if a.creation and getdate(a.creation) <= getdate(dt) and a.due_date and getdate(a.due_date) < getdate(dt):
                    if not is_completed_by_dt:
                        overdue_dt += 1
                        
        completion_rate_history.append(int((completed_dt / total_dt) * 100) if total_dt > 0 else 0)
        overdue_assignments_history.append(overdue_dt)
        
    # Current values are simply the most recent snapshot
    active_learners = active_learners_history[-1]
    completion_rate = completion_rate_history[-1]
    overdue_assignments = overdue_assignments_history[-1]
    
    return {
        "activeLearners": active_learners,
        "activeLearnersTrend": "+5% this month",
        "activeLearnersHistory": active_learners_history,
        
        "completionRate": completion_rate,
        "completionRateTrend": "Trending steady",
        "completionRateHistory": completion_rate_history,
        
        "overdueAssignments": overdue_assignments,
        "overdueAssignmentsTrend": "Needs review",
        "overdueAssignmentsHistory": overdue_assignments_history,
        
        "complianceCompletion": completion_rate,
        "complianceCompletionTrend": "On track",
        "complianceCompletionHistory": completion_rate_history
    }

@frappe.whitelist(allow_guest=True)
def get_department_performance():
    teams = frappe.get_all("LMS Team", fields=["name", "team_name"])
    results = []
    for t in teams:
        # Get members of this team
        members = frappe.get_all("LMS Team Member", filters={"parent": t.name}, fields=["user"])
        member_emails = [m.user for m in members]
        
        if not member_emails:
            continue
            
        trackers = frappe.get_all("LMS Module Tracker", filters={"user": ["in", member_emails]}, fields=["status", "total_score"])
        total_t = len(trackers)
        completed = len([tr for tr in trackers if tr.status == "Completed"])
        
        c_rate = int((completed / total_t) * 100) if total_t > 0 else 0
        avg_score = sum([tr.total_score or 0 for tr in trackers]) / total_t if total_t > 0 else 0
        
        results.append({
            "name": t.team_name,
            "completionRate": c_rate,
            "avgScore": int(avg_score),
            "overdueLearners": 0, # simplified
            "criticalOverdue": False
        })
    return results

@frappe.whitelist(allow_guest=True)
def get_upcoming_deadlines():
    assignments = frappe.get_all("LMS Module Assignment", 
        fields=["name", "title", "due_date", "is_mandatory", "assignee_type"],
        limit=5,
        order_by="due_date asc"
    )
    results = []
    for a in assignments:
        results.append({
            "id": a.name,
            "name": a.title,
            "type": "Module",
            "date": str(a.due_date) if a.due_date else "No Date",
            "critical": bool(a.is_mandatory)
        })
    return results

@frappe.whitelist(allow_guest=True)
def get_recently_assigned():
    assignments = frappe.get_all("LMS Module Assignment", 
        fields=["name", "title", "assignment_date", "due_date", "assignee_type"],
        limit=5,
        order_by="assignment_date desc"
    )
    results = []
    for a in assignments:
        # Count trackers assigned to this assignment
        trackers = frappe.get_all("LMS Module Tracker", filters={"assignment": a.name}, fields=["status"])
        total_assigned = len(trackers)
        completed = len([t for t in trackers if t.status == "Completed"])
        progress = int((completed / total_assigned) * 100) if total_assigned > 0 else 0
        
        results.append({
            "id": a.name,
            "name": a.title,
            "assignedLearners": total_assigned,
            "dueDate": str(a.due_date) if a.due_date else "No Date",
            "progress": progress,
            "actions": ["Remind", "View Details"]
        })
    return results

@frappe.whitelist(allow_guest=True)
def get_learning_insights():
    insights = []
    
    # Analyze Team performance for insights
    teams = frappe.get_all("LMS Team", fields=["name", "team_name"])
    lowest_team = None
    lowest_score = 100
    highest_team = None
    highest_score = 0
    
    for t in teams:
        members = frappe.get_all("LMS Team Member", filters={"parent": t.name}, fields=["user"])
        member_emails = [m.user for m in members]
        if not member_emails: continue
        
        trackers = frappe.get_all("LMS Module Tracker", filters={"user": ["in", member_emails]}, fields=["total_score"])
        total = len(trackers)
        if total == 0: continue
        
        avg = sum([tr.total_score or 0 for tr in trackers]) / total
        
        if avg <= lowest_score:
            lowest_score = avg
            lowest_team = t.team_name
        if avg >= highest_score:
            highest_score = avg
            highest_team = t.team_name
            
    if lowest_team:
        insights.append({
            "id": "1",
            "type": "insight",
            "title": f"Low Engagement in {lowest_team}",
            "description": f"The **{lowest_team}** team has an average score of {int(lowest_score)}%, currently the lowest in the company. Consider sending a reminder.",
            "action": "Send Reminder",
            "critical": True,
            "icon": "TrendingDown"
        })
        
    if highest_team:
        insights.append({
            "id": "2",
            "type": "achievement",
            "title": f"{highest_team} Team Excelled",
            "description": f"The **{highest_team}** team is leading the board with an impressive average assessment score of {int(highest_score)}%.",
            "action": "View Details",
            "critical": False,
            "icon": "Trophy"
        })
        
    # Overdue/In Progress insight
    in_progress = frappe.db.count("LMS Module Tracker", {"status": "In Progress"})
    if in_progress > 0:
        insights.append({
            "id": "3",
            "type": "recommendation",
            "title": "Boost Completion Rates",
            "description": f"There are currently {in_progress} active learners marked as 'In Progress'. Sending a quick follow-up could help boost overall completion.",
            "action": "Review Assignments",
            "critical": False,
            "icon": "Lightbulb"
        })
        
    return insights

@frappe.whitelist(allow_guest=True)
def get_learning_content_summary():
    passed = frappe.db.count("LMS Module Tracker", {"status": "Completed"})
    failed = frappe.db.count("LMS Module Tracker", {"status": "Failed"})
    in_progress = frappe.db.count("LMS Module Tracker", {"status": "In Progress"})
    not_started = frappe.db.count("LMS Module Tracker", {"status": "Not started"})
    
    # Let's consider overdue as in progress but past due date on the assignment
    # We seeded one earlier
    trackers = frappe.get_all("LMS Module Tracker", filters={"status": ["in", ["In Progress", "Not started"]]}, fields=["assignment"])
    overdue_count = 0
    for t in trackers:
        if t.assignment:
            due = frappe.db.get_value("LMS Module Assignment", t.assignment, "due_date")
            if due and getdate(due) < getdate(today()):
                overdue_count += 1
                
    # If a tracker is overdue, subtract from its original status pool to prevent double counting visually
    # For simplicity, we just return the counts
    return [
        {"name": "Passed", "value": passed or 0},
        {"name": "Failed", "value": failed or 0},
        {"name": "Overdue", "value": overdue_count or 0},
        {"name": "In Progress", "value": in_progress or 0},
        {"name": "Not Started", "value": not_started or 0}
    ]

@frappe.whitelist(allow_guest=True)
def get_assessment_performance():
    trackers = frappe.get_all("LMS Module Tracker", fields=["status", "total_score"])
    total_t = len(trackers)
    
    if total_t == 0:
        return {"averageScore": 0, "passRate": 0, "needsRetake": 0}
        
    avg_score = sum([t.total_score or 0 for t in trackers]) / total_t
    passed = len([t for t in trackers if t.status == "Completed"])
    failed = len([t for t in trackers if t.status == "Failed"])
    
    return {
        "averageScore": int(avg_score),
        "passRate": int((passed / total_t) * 100),
        "needsRetake": failed
    }

@frappe.whitelist(allow_guest=True)
def get_needs_attention_metrics():
    # Overdue Learning
    trackers = frappe.get_all("LMS Module Tracker", filters={"status": ["in", ["In Progress", "Not started"]]}, fields=["assignment"])
    overdue_learning = 0
    for t in trackers:
        if t.assignment:
            due = frappe.db.get_value("LMS Module Assignment", t.assignment, "due_date")
            if due and getdate(due) < getdate(today()):
                overdue_learning += 1
                
    # Inactive Learners (simulated by checking users with no trackers)
    total_users = frappe.db.count("User")
    active_users = len(set([t.user for t in frappe.get_all("LMS Module Tracker", fields=["user"])]))
    inactive_learners = total_users - active_users

    # Low assessment scores (Trackers with score < 60)
    low_scores = frappe.db.count("LMS Module Tracker", {"total_score": ["<", 60], "status": "Failed"})

    return {
        "overdueLearning": overdue_learning or 0,
        "inactiveLearners": inactive_learners or 0,
        "lowAssessmentScores": low_scores or 0
    }

@frappe.whitelist(allow_guest=True)
def get_onboarding_status():
    thirty_days_ago = add_days(today(), -30)
    new_users = frappe.db.count("User", {"creation": [">=", thirty_days_ago]})
    
    if new_users == 0:
        return {
            "count": 0,
            "title": "Employee Onboarding: ",
            "description": "No new employees onboarded in the last 30 days."
        }
        
    return {
        "count": new_users,
        "title": "New Employee Onboarding: ",
        "description": f"Track the onboarding progress of {new_users} new employees."
    }
