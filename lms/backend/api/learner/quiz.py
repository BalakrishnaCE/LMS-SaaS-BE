"""
Learner Quiz Submission API

Handles saving learner responses for both:
  - LMS Quiz Content blocks  (quiz-type content embedded in chapters)
  - LMS Assessment Content blocks  (standalone QA/assessment-type content)

Submissions are stored in the `LMS Quiz Submission` doctype with per-question
responses in the `LMS Quiz Response` child table.
"""

import json
import frappe


@frappe.whitelist()
def submit_quiz(module, content_reference, score=None, passed=0, time_taken=0, responses=None):
    """
    Submit a learner's quiz / assessment attempt.

    Args:
        module            (str): LMS Module name (e.g. "Advanced Leadership Training")
        content_reference (str): Name of the content block (e.g. "BLK-0113").
                                 Can be either an LMS Quiz Content or an LMS Assessment Content doc.
        score             (float|None): Computed percentage score. None if pending manual review.
        passed            (int): 1 if the learner passed, 0 otherwise.
        time_taken        (int): Seconds spent on the quiz.
        responses         (list|str): JSON-serialised list of per-question responses.

    Returns:
        str: Name of the newly created LMS Quiz Submission document.
    """
    if responses is None:
        responses = []

    if isinstance(responses, str):
        responses = json.loads(responses)

    user = frappe.session.user

    # Admins previewing quizzes in admin panel should not have submissions tracked
    from lms.backend.api.learner.progress import _is_admin_user
    if _is_admin_user(user):
        return {"status": "skipped", "reason": "admin user"}

    # ── 1. Ensure a tracker exists ────────────────────────────────────────────
    tracker = frappe.get_all(
        "LMS Module Tracker",
        filters={"user": user, "module": module},
        limit=1

    )
    if not tracker:
        tracker_doc = frappe.get_doc({
            "doctype": "LMS Module Tracker",
            "user": user,
            "module": module,
            "status": "In Progress",
            "started_on": frappe.utils.now_datetime()
        })
        tracker_doc.insert(ignore_permissions=True)
        tracker_name = tracker_doc.name
    else:
        tracker_name = tracker[0].name

    # ── 2. Resolve the actual LMS Quiz from the content block ─────────────────
    # content_reference points to either LMS Quiz Content or LMS Assessment Content.
    # We detect which one to get the correct `quiz` / `assessment` field value and
    # to set the right `content_type` on the Dynamic Link in LMS Content Progress.
    quiz_id = frappe.db.get_value("LMS Quiz Content", content_reference, "quiz")
    actual_content_type = "LMS Quiz Content"

    if not quiz_id:
        quiz_id = frappe.db.get_value("LMS Assessment Content", content_reference, "assessment")
        actual_content_type = "LMS Assessment Content"

    if not quiz_id:
        frappe.throw(
            f"Could not find an associated LMS Quiz for Content Reference: {content_reference}"
        )

    # ── 3. Create the submission ──────────────────────────────────────────────
    submission = frappe.get_doc({
        "doctype": "LMS Quiz Submission",
        "user": user,
        "quiz": quiz_id,
        "enrollment": tracker_name,
        "score": score,
        "passed": passed,
        "time_taken": time_taken,
        "submitted_on": frappe.utils.now_datetime()
    })

    for resp in responses:
        # Skip responses where question ID is missing
        if resp.get("question") is None:
            continue

        question_id = str(resp.get("question"))
        selected_option = resp.get("selected_option") or ""

        # ── Server-side is_correct verification ───────────────────────────────
        # Do NOT blindly trust the frontend's is_correct value.
        # Instead, look up the question and verify against the stored options.
        is_correct = 0
        try:
            q_doc = frappe.get_doc("LMS Quiz Question", question_id)
            auto_graded_types = ("Single Choice", "True/False", "Multiple Choice", "Fill in the Blank")

            if q_doc.question_type in auto_graded_types and q_doc.options:
                if q_doc.question_type == "Multiple Choice":
                    # selected_option is comma-joined selected texts
                    selected_texts = set(t.strip() for t in selected_option.split(",") if t.strip())
                    correct_texts = set(
                        opt.option_text.strip()
                        for opt in q_doc.options
                        if opt.is_correct
                    )
                    if selected_texts and selected_texts == correct_texts:
                        is_correct = 1
                else:
                    # Single choice / True/False / Fill in the Blank with options
                    for opt in q_doc.options:
                        if opt.option_text.strip() == selected_option.strip() and opt.is_correct:
                            is_correct = 1
                            break
            else:
                # Scenario Based / open-ended FitB — manual grading, no auto is_correct
                is_correct = 0
        except Exception:
            # Fall back to frontend value if question lookup fails
            is_correct = int(resp.get("is_correct", 0) or 0)

        submission.append("responses", {
            "question": question_id,
            "selected_option": selected_option,
            "is_correct": is_correct
        })

    submission.insert(ignore_permissions=True)

    # ── 4. Update content progress ────────────────────────────────────────────
    # Pass the correct content_type so the Dynamic Link validation passes.
    from lms.backend.api.learner.progress import update_content_progress
    update_content_progress(
        module,
        content_reference,
        content_type=actual_content_type,
        status="Completed",
        score=score
    )

    return submission.name


@frappe.whitelist()
def get_quiz_submissions(module, content_reference):
    """
    Return the learner's previous submission history for a content block.

    Returns a list of submissions (newest first) with score, passed, and time_taken.
    """
    user = frappe.session.user

    quiz_id = frappe.db.get_value("LMS Quiz Content", content_reference, "quiz")
    if not quiz_id:
        quiz_id = frappe.db.get_value("LMS Assessment Content", content_reference, "assessment")

    if not quiz_id:
        return []

    submissions = frappe.get_all(
        "LMS Quiz Submission",
        filters={"user": user, "quiz": quiz_id},
        fields=["name", "score", "passed", "time_taken", "submitted_on", "extra_attempts_granted"],
        order_by="submitted_on desc"
    )

    return submissions
