import frappe
from frappe.utils import today

def create_test_data():
    frappe.flags.in_test = True
    
    # 1. Ensure Quiz exists
    quiz_title = "Sales Call Quality"
    if not frappe.db.exists("LMS Quiz", {"title": quiz_title}):
        quiz = frappe.get_doc({
            "doctype": "LMS Quiz",
            "title": quiz_title,
            "passing_percentage": 70,
            "evaluation_method": "Manual review",
            "is_passing_required": 1
        })
        quiz.insert(ignore_permissions=True)
        quiz_name = quiz.name
    else:
        quiz_name = frappe.db.get_value("LMS Quiz", {"title": quiz_title}, "name")
        # Ensure it has manual review
        frappe.db.set_value("LMS Quiz", quiz_name, "evaluation_method", "Manual review")

    # 2. Ensure User 'sdgs' exists
    # Or just use any existing user that is a learner in the team. Let's find one.
    tl_user = "Administrator" # Assuming we're logged in as Admin
    team_members = frappe.get_all("LMS Team Member", fields=["user", "parent"])
    learner_email = None
    if team_members:
        # Just pick the first one, or see if 'sdgs' exists
        for tm in team_members:
            if "sdgs" in tm.user:
                learner_email = tm.user
                break
        if not learner_email:
            learner_email = team_members[0].user
    else:
        # Create a user and a team
        learner_email = "sdgs@example.com"
        if not frappe.db.exists("User", learner_email):
            user = frappe.get_doc({
                "doctype": "User",
                "email": learner_email,
                "first_name": "sdgs",
                "send_welcome_email": 0
            })
            user.insert(ignore_permissions=True)
            
        if not frappe.db.exists("LMS Team", "Test Team"):
            team = frappe.get_doc({
                "doctype": "LMS Team",
                "team_name": "Test Team",
                "team_leader": tl_user
            })
            team.append("members", {"user": learner_email})
            team.insert(ignore_permissions=True)
        else:
            team = frappe.get_doc("LMS Team", "Test Team")
            if not any(m.user == learner_email for m in team.members):
                team.append("members", {"user": learner_email})
                team.save(ignore_permissions=True)

    # 3. Create LMS Quiz Submission
    submission = frappe.get_doc({
        "doctype": "LMS Quiz Submission",
        "user": learner_email,
        "quiz": quiz_name,
        "score": 0,
        "submitted_on": today(),
        # enrollment is required, but we can just skip it or create a dummy tracker if needed.
        # Let's see if enrollment is mandatory. It says "reqd": 1 in JSON.
    })
    
    # We need a tracker for enrollment
    tracker_name = None
    if frappe.db.exists("LMS Module Tracker", {"user": learner_email}):
        tracker_name = frappe.db.get_list("LMS Module Tracker", {"user": learner_email})[0].name
    else:
        # Create dummy tracker
        tracker = frappe.get_doc({
            "doctype": "LMS Module Tracker",
            "user": learner_email,
            "status": "In Progress"
        })
        tracker.insert(ignore_permissions=True)
        tracker_name = tracker.name
        
    submission.enrollment = tracker_name
    
    # Add a dummy response
    q_name = None
    if frappe.db.exists("LMS Quiz Question", {"question_type": "Free Text"}):
        q_name = frappe.db.get_list("LMS Quiz Question", {"question_type": "Free Text"})[0].name
    else:
        q = frappe.get_doc({
            "doctype": "LMS Quiz Question",
            "question_text": "How did you handle the objections?",
            "question_type": "Scenario Based",
            "score": 5
        })
        q.insert(ignore_permissions=True)
        q_name = q.name
        
    submission.append("responses", {
        "question": q_name,
        "selected_option": "I listened and empathized."
    })
    
    submission.insert(ignore_permissions=True)
    frappe.db.commit()
    print("Test data created successfully.")

