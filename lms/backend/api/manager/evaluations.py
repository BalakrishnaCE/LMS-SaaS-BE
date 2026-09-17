import frappe
import json
from frappe.utils import getdate

@frappe.whitelist()
def get_qa_submission_details(submission_id):
    """
    Fetch all details for a QA Assessment Evaluation including:
    - Submission details
    - Learner details
    - Quiz Title
    - Each Question text and the Learner's Response
    """
    if not frappe.has_permission("LMS Quiz Submission", "read", doc=submission_id):
        frappe.throw("Not permitted", frappe.PermissionError)
        
    sub = frappe.get_doc("LMS Quiz Submission", submission_id)
    learner_name = frappe.db.get_value("User", sub.user, "full_name") or sub.user
    quiz_title, passing_percentage = frappe.db.get_value("LMS Quiz", sub.quiz, ["title", "passing_percentage"]) or (sub.quiz, 70)
    
    questions = []
    
    for resp in sub.responses:
        q_doc = frappe.get_doc("LMS Quiz Question", resp.question)
        
        # Check if question requires manual evaluation
        requires_manual = False
        if q_doc.question_type == "Scenario Based":
            requires_manual = True
        elif q_doc.question_type == "Fill in the Blank" and len(q_doc.options) == 0:
            requires_manual = True
            
        if not requires_manual:
            continue
        
        # Load any existing evaluation data if present
        eval_data = {}
        if resp.evaluation_data:
            try:
                eval_data = json.loads(resp.evaluation_data)
            except:
                pass
                
        # Build criteria from the question's options (each option = a rubric criterion for Scenario Based)
        criteria = []
        if q_doc.question_type == "Scenario Based":
            for opt in q_doc.options:
                criteria.append({
                    "name": opt.option_text,
                    "max_score": int(opt.score) if opt.score else 5
                })
        
        # If no criteria defined, fall back to a single generic criterion with max_score=5
        if not criteria and q_doc.question_type == "Scenario Based":
            criteria = [{"name": "Overall", "max_score": 5}]
                
        questions.append({
            "response_id": resp.name,
            "question_text": q_doc.question_text,
            "question_type": q_doc.question_type,
            "learner_response": resp.selected_option,
            "manual_score": resp.manual_score or 0,
            "evaluation_data": eval_data,
            "criteria": criteria,
            "max_score": sum(c["max_score"] for c in criteria) if criteria else 5
        })
        
    return {
        "submission_id": sub.name,
        "quiz_title": quiz_title,
        "learner_name": learner_name,
        "learner_id": sub.user,
        "due_date": frappe.utils.formatdate(sub.submitted_on, "MMM d, YYYY") if sub.submitted_on else "",
        "passing_percentage": passing_percentage,
        "overall_feedback": sub.evaluation_feedback or "",
        "questions": questions
    }

@frappe.whitelist()
def save_qa_evaluation(submission_id, evaluations, overall_feedback=""):
    """
    Save the QA evaluation scores and feedback for a given submission.
    Recalculates the final score by combining manual scores and auto-graded scores.
    """
    if not frappe.has_permission("LMS Quiz Submission", "write", doc=submission_id):
        frappe.throw("Not permitted", frappe.PermissionError)
        
    if isinstance(evaluations, str):
        evaluations = json.loads(evaluations)
        
    sub = frappe.get_doc("LMS Quiz Submission", submission_id)
    sub.evaluation_feedback = overall_feedback
    
    total_questions = len(sub.responses)
    
    # 1. Update manual scores in child table
    for eval_item in evaluations:
        resp_id = eval_item.get("response_id")
        score = eval_item.get("manual_score", 0)
        eval_data = eval_item.get("evaluation_data", {})
        
        for resp in sub.responses:
            if resp.name == resp_id:
                resp.manual_score = score
                resp.evaluation_data = json.dumps(eval_data)
                break
                
    # 2. Recalculate total score combining auto-graded and manual scores
    total_score = 0
    for resp in sub.responses:
        q_doc = frappe.get_doc("LMS Quiz Question", resp.question)
        
        requires_manual = False
        if q_doc.question_type == "Scenario Based":
            requires_manual = True
        elif q_doc.question_type == "Fill in the Blank" and len(q_doc.options) == 0:
            requires_manual = True
            
        if requires_manual:
            total_score += resp.manual_score or 0
        else:
            # Auto-graded questions: 1 point if correct, 0 if not
            if resp.is_correct:
                total_score += 1
                
    # 3. Calculate percentage using actual max possible per question
    max_possible = 0
    for resp in sub.responses:
        q_doc = frappe.get_doc("LMS Quiz Question", resp.question)
        
        requires_manual = (
            q_doc.question_type == "Scenario Based" or
            (q_doc.question_type == "Fill in the Blank" and len(q_doc.options) == 0)
        )
        
        if requires_manual:
            # Max = sum of each criterion's defined max_score
            if q_doc.options:
                max_possible += sum(int(opt.score) if opt.score else 5 for opt in q_doc.options)
            else:
                max_possible += 5  # fallback if no criteria defined
        else:
            max_possible += 1  # auto-graded: 1 point max
                
    if max_possible > 0:
        sub.score = (total_score / max_possible) * 100
    else:
        sub.score = 0
        
    # If the score is >= passing_percentage, pass it.
    passing_req = frappe.db.get_value("LMS Quiz", sub.quiz, ["is_passing_required", "passing_percentage"], as_dict=True)
    if passing_req and passing_req.is_passing_required:
        sub.passed = 1 if sub.score >= passing_req.passing_percentage else 0
    else:
        sub.passed = 1
        
    sub.flags.ignore_links = True
    sub.save(ignore_permissions=True)
    
    # ── Propagate the evaluated score back to LMS Content Progress ────────────
    # The submission stores `enrollment` = LMS Module Tracker name.
    # We need to find the LMS Assessment Content block that triggered this quiz,
    # then update the matching LMS Content Progress row's score so that the
    # module tracker's total_score is recalculated correctly.
    try:
        tracker_name = sub.enrollment
        if tracker_name and frappe.db.exists("LMS Module Tracker", tracker_name):
            # Find the LMS Assessment Content block linked to this quiz
            assessment_content = frappe.db.get_value(
                "LMS Assessment Content",
                {"assessment": sub.quiz},
                "name"
            )
            if assessment_content:
                cp_list = frappe.get_all(
                    "LMS Content Progress",
                    filters={"parent": tracker_name, "content_reference": assessment_content},
                    limit=1
                )
                if cp_list:
                    cp_doc = frappe.get_doc("LMS Content Progress", cp_list[0].name)
                    cp_doc.score = sub.score
                    cp_doc.status = "Completed"
                    cp_doc.is_completed = 1
                    cp_doc.save(ignore_permissions=True)
                    
                    # Re-save tracker so update_progress() recalculates total_score
                    tracker_doc = frappe.get_doc("LMS Module Tracker", tracker_name)
                    if tracker_doc.status == "Excluded":
                        tracker_doc.status = "In Progress"
                    tracker_doc.save(ignore_permissions=True)
    except Exception as e:
        frappe.log_error(f"save_qa_evaluation: failed to propagate score to tracker: {e}", "QA Evaluation")
        
    frappe.db.commit()
    
    return True

