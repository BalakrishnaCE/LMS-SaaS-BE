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
    quiz_title = frappe.db.get_value("LMS Quiz", sub.quiz, "title") or sub.quiz
    
    questions = []
    
    for resp in sub.responses:
        q_doc = frappe.get_doc("LMS Quiz Question", resp.question)
        
        # Load any existing evaluation data if present
        eval_data = {}
        if resp.evaluation_data:
            try:
                eval_data = json.loads(resp.evaluation_data)
            except:
                pass
                
        questions.append({
            "response_id": resp.name,
            "question_text": q_doc.question_text,
            "question_type": q_doc.question_type,
            "learner_response": resp.selected_option,
            "manual_score": resp.manual_score or 0,
            "evaluation_data": eval_data
        })
        
    return {
        "submission_id": sub.name,
        "quiz_title": quiz_title,
        "learner_name": learner_name,
        "due_date": frappe.utils.formatdate(sub.submitted_on, "MMM d, YYYY") if sub.submitted_on else "",
        "questions": questions
    }

@frappe.whitelist()
def save_qa_evaluation(submission_id, evaluations):
    """
    Saves the manual evaluation scores and feedback for each response.
    `evaluations` should be a list of dicts:
    [{ "response_id": "...", "manual_score": 4, "evaluation_data": {...} }]
    """
    if not frappe.has_permission("LMS Quiz Submission", "write", doc=submission_id):
        frappe.throw("Not permitted", frappe.PermissionError)
        
    if isinstance(evaluations, str):
        evaluations = json.loads(evaluations)
        
    sub = frappe.get_doc("LMS Quiz Submission", submission_id)
    
    total_manual_score = 0
    total_questions = len(sub.responses)
    
    for eval_item in evaluations:
        resp_id = eval_item.get("response_id")
        score = eval_item.get("manual_score", 0)
        eval_data = eval_item.get("evaluation_data", {})
        
        # Find the row in child table
        for resp in sub.responses:
            if resp.name == resp_id:
                resp.manual_score = score
                resp.evaluation_data = json.dumps(eval_data)
                break
                
        total_manual_score += score
        
    # Calculate percentage based on total questions (assuming 5 points max per question)
    max_possible = total_questions * 5
    if max_possible > 0:
        sub.score = (total_manual_score / max_possible) * 100
    else:
        sub.score = 0
        
    # If the score is >= passing_percentage, pass it.
    passing_req = frappe.db.get_value("LMS Quiz", sub.quiz, ["is_passing_required", "passing_percentage"], as_dict=True)
    if passing_req and passing_req.is_passing_required:
        sub.passed = 1 if sub.score >= passing_req.passing_percentage else 0
    else:
        sub.passed = 1
        
    sub.save(ignore_permissions=True)
    frappe.db.commit()
    
    return True
