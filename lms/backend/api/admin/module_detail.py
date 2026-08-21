import frappe
import json
from frappe.utils import today, add_days, getdate, now

@frappe.whitelist(allow_guest=True)
def get_ai_insights(module_id):
    trackers = frappe.get_all(
        "LMS Module Tracker",
        filters={"module": module_id},
        fields=["status", "user", "total_score", "started_on", "completed_on"]
    )

    total = len(trackers)
    if total == 0:
        return {"insights": [
            "No learner data yet. Assign this module to learners to see insights."
        ]}

    completed = [t for t in trackers if t.status == "Completed"]
    in_prog   = [t for t in trackers if t.status == "In Progress"]
    not_started = total - len(completed) - len(in_prog)

    insights = []

    completion_rate = round(len(completed) / total * 100)
    if completion_rate >= 80:
        insights.append(f"{completion_rate}% of learners have completed this module — excellent engagement!")
    elif completion_rate >= 50:
        insights.append(f"{completion_rate}% completion rate. Consider sending a reminder to the remaining learners.")
    else:
        insights.append(f"Only {completion_rate}% completion rate. This module may need attention — consider reviewing its difficulty or length.")

    scores = [t.total_score for t in completed if t.total_score is not None]
    if scores:
        avg_score = round(sum(scores) / len(scores))
        if avg_score < 60:
            insights.append(f"Average assessment score is {avg_score}% — learners may be struggling with the content.")
        elif avg_score >= 85:
            insights.append(f"Strong average assessment score of {avg_score}% among completions.")
        else:
            insights.append(f"Average assessment score is {avg_score}%.")

    if not_started > 0:
        insights.append(f"{not_started} learner{'s' if not_started > 1 else ''} haven't started yet. A nudge notification could help.")

    stalled = [t for t in in_prog if not t.total_score]
    if len(stalled) > 0:
        insights.append(f"{len(stalled)} learner{'s' if len(stalled) > 1 else ''} started but haven't completed any assessments.")

    return {"insights": insights[:4]}


@frappe.whitelist(allow_guest=True)
def get_assessment_analytics(module_id):
    import re
    module = frappe.get_doc("LMS Module", module_id)
    if not module.final_assessments:
        return {"stats": {"passRate": 0, "averageScore": 0, "learnersRetested": 0, "retestPercentage": 0}, "missedQuestion": None, "analytics": []}
    
    quiz_name = module.final_assessments[0].assessment
    if not quiz_name:
        return {"stats": {"passRate": 0, "averageScore": 0, "learnersRetested": 0, "retestPercentage": 0}, "missedQuestion": None, "analytics": []}
    
    trackers = frappe.get_all("LMS Module Tracker", filters={"module": module_id}, pluck="name")
    if not trackers:
        return {"stats": {"passRate": 0, "averageScore": 0, "learnersRetested": 0, "retestPercentage": 0}, "missedQuestion": None, "analytics": []}
        
    submissions = frappe.get_all("LMS Quiz Submission", 
        filters={"quiz": quiz_name, "enrollment": ["in", trackers]},
        fields=["name", "user", "score", "passed"]
    )
    
    if not submissions:
        return {"stats": {"passRate": 0, "averageScore": 0, "learnersRetested": 0, "retestPercentage": 0}, "missedQuestion": None, "analytics": []}

    user_submissions = {}
    total_score = 0
    passed_count = 0

    for sub in submissions:
        total_score += sub.score
        if sub.passed:
            passed_count += 1
            
        if sub.user not in user_submissions:
            user_submissions[sub.user] = []
        user_submissions[sub.user].append(sub)

    unique_learners = len(user_submissions)
    unique_passed = sum(1 for user, subs in user_submissions.items() if any(s.passed for s in subs))
    passRate = round((unique_passed / unique_learners) * 100) if unique_learners > 0 else 0
    averageScore = round(total_score / len(submissions)) if submissions else 0
    learnersRetested = sum(1 for user, subs in user_submissions.items() if len(subs) > 1)
    retestPercentage = round((learnersRetested / unique_learners) * 100) if unique_learners > 0 else 0
    
    sub_names = [s.name for s in submissions]
    responses = frappe.get_all("LMS Quiz Response", 
        filters={"parent": ["in", sub_names]},
        fields=["question", "is_correct"]
    )
    
    question_stats = {}
    for r in responses:
        q = r.question
        if q not in question_stats:
            question_stats[q] = {"total": 0, "correct": 0}
        question_stats[q]["total"] += 1
        if r.is_correct:
            question_stats[q]["correct"] += 1
            
    analytics = []
    most_missed = None
    highest_miss_rate = -1

    if question_stats:
        questions = frappe.get_all("LMS Quiz Question", 
            filters={"name": ["in", list(question_stats.keys())]},
            fields=["name", "question_text", "question_type"]
        )
        
        for q in questions:
            stats = question_stats.get(str(q.name), {"total": 0, "correct": 0})
            pass_pct = round((stats["correct"] / stats["total"]) * 100) if stats["total"] > 0 else 0
            miss_rate = 100 - pass_pct
            
            q_type_label = "Multiple Choice"
            if q.question_type == "Single Choice":
                q_type_label = "Multiple Choice"
            elif q.question_type == "Multiple Choice":
                q_type_label = "Multiple Selection"
            elif q.question_type == "True/False":
                q_type_label = "True/False"
                
            raw_text = re.sub(r'<[^>]+>', '', q.question_text or '').strip()

            is_most_missed = False
            if miss_rate > highest_miss_rate and miss_rate > 0:
                highest_miss_rate = miss_rate
                most_missed = {
                    "id": str(q.name),
                    "text": "Most Missed Question",
                    "question": raw_text[:97] + "..." if len(raw_text) > 100 else raw_text,
                    "percentage": miss_rate
                }
                
            analytics.append({
                "id": str(q.name),
                "question": raw_text,
                "type": q_type_label,
                "passRate": pass_pct,
                "isMostMissed": False
            })
            
        if most_missed:
            for a in analytics:
                if a["id"] == most_missed["id"]:
                    a["isMostMissed"] = True

    return {
        "stats": {
            "passRate": passRate,
            "averageScore": averageScore,
            "learnersRetested": learnersRetested,
            "retestPercentage": retestPercentage
        },
        "missedQuestion": most_missed,
        "analytics": analytics
    }


@frappe.whitelist()
def update_question(question_id, question_text, options, explanation=""):
    import json
    if isinstance(options, str):
        options = json.loads(options)
        
    doc = frappe.get_doc("LMS Quiz Question", question_id)
    doc.question_text = question_text
    doc.explanation = explanation
    
    doc.set("options", [])
    for opt in options:
        doc.append("options", {
            "option_text": opt.get("text"),
            "is_correct": opt.get("is_correct", 0)
        })
        
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return "success"


@frappe.whitelist()
def delete_question(quiz_name, question_id):
    if frappe.db.exists("LMS Quiz", quiz_name):
        quiz = frappe.get_doc("LMS Quiz", quiz_name)
        new_questions = [q for q in quiz.questions if str(q.quiz_question) != str(question_id)]
        quiz.set("questions", new_questions)
        quiz.save(ignore_permissions=True)
        
    frappe.db.sql("DELETE FROM `tabLMS Quiz Response` WHERE question=%s", (question_id,))
    frappe.delete_doc("LMS Quiz Question", question_id, ignore_permissions=True, force=1)
    frappe.db.commit()
    return "success"


@frappe.whitelist(allow_guest=False)
def update_module_settings(module_id, settings):
    import json
    if not frappe.has_permission("LMS Module", "write", doc=module_id):
        frappe.throw("Not permitted", frappe.PermissionError)
        
    module = frappe.get_doc("LMS Module", module_id)
    
    try:
        settings_dict = json.loads(settings)
        
        for key, value in settings_dict.items():
            if module.meta.has_field(key):
                module.db_set(key, 1 if value else 0)
                
        return {"message": "success"}
    except Exception as e:
        frappe.log_error(f"Error in update_module_settings: {str(e)}")
        return {"error": str(e)}


