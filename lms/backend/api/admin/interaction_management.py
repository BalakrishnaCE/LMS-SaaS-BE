import frappe
import json
from lms.backend.api.common.interaction_management import (
    _get_interactive_video_content,
    _migrate_to_interactive_video,
    _create_quiz_for_knowledge_check,
    _get_all_elements_sorted
)

@frappe.whitelist(allow_guest=False)
def add_interaction(
    chapter_name,
    interaction_type_name,
    timeline_seconds=0,
    element_text=None,
    secondary_text=None,
    options=None,
    is_required=False,
    end_time_seconds=None,
    pause_video=True,
    display_mode="immediate",
    correct_action="continue",
    incorrect_action="message",
    correct_jump_seconds=None,
    incorrect_jump_seconds=None,
    require_correct=False,
    feedback_correct=None,
    feedback_incorrect=None,
    sort_order=0,
    x_coordinate=None,
    y_coordinate=None,
):
    if not chapter_name or not interaction_type_name:
        frappe.throw("Chapter Name and Interaction Type are required")

    timeline_seconds = float(timeline_seconds or 0)

    chapter = frappe.get_doc("LMS Chapter", chapter_name)
    interactive_content = _get_interactive_video_content(chapter)

    if not interactive_content:
        interactive_content = _migrate_to_interactive_video(chapter)

    if not interactive_content:
        frappe.throw("Could not find or create Interactive Video Content for this chapter")

    if options and isinstance(options, str):
        options = json.loads(options)

    frappe.log_error(f"ADD INTERACTION DEBUG: inc_action={incorrect_action}, inc_jump={incorrect_jump_seconds}", "Add Interaction Payload")
    element_data = {
        "interaction_type": interaction_type_name,
        "timeline_seconds": timeline_seconds,
        "element_text": element_text or "",
        "secondary_text": secondary_text or "",
        "is_required": 1 if is_required else 0,
        "end_time_seconds": float(end_time_seconds) if end_time_seconds else None,
        "pause_video": 1 if pause_video in (True, 1, "1", "true", "True") else 0,
        "display_mode": display_mode or "immediate",
        "correct_action": correct_action or "continue",
        "incorrect_action": incorrect_action or "message",
        "correct_jump_seconds": float(correct_jump_seconds) if correct_jump_seconds is not None and str(correct_jump_seconds).strip() != "" else None,
        "incorrect_jump_seconds": float(incorrect_jump_seconds) if incorrect_jump_seconds is not None and str(incorrect_jump_seconds).strip() != "" else None,
        "require_correct": 1 if require_correct in (True, 1, "1", "true", "True") else 0,
        "feedback_correct": feedback_correct or "",
        "feedback_incorrect": feedback_incorrect or "",
        "sort_order": int(sort_order or 0),
        "x_coordinate": float(x_coordinate) if x_coordinate else None,
        "y_coordinate": float(y_coordinate) if y_coordinate else None,
    }

    if interaction_type_name == "Knowledge Check" and options:
        quiz_doc = _create_quiz_for_knowledge_check(element_text, options, is_required)
        element_data["linked_record_type"] = "LMS Quiz"
        element_data["linked_record_name"] = quiz_doc.name

    elif interaction_type_name == "Poll" and options:
        element_data["secondary_text"] = json.dumps(options)

    interactive_content.append("interactive_elements", element_data)
    interactive_content.save(ignore_permissions=True)

    return _get_all_elements_sorted(interactive_content)


@frappe.whitelist(allow_guest=False)
def update_interaction(
    chapter_name,
    element_idx,
    interaction_type_name=None,
    timeline_seconds=None,
    element_text=None,
    secondary_text=None,
    options=None,
    is_required=False,
    end_time_seconds=None,
    pause_video=None,
    display_mode=None,
    correct_action=None,
    incorrect_action=None,
    correct_jump_seconds=None,
    incorrect_jump_seconds=None,
    require_correct=None,
    feedback_correct=None,
    feedback_incorrect=None,
    sort_order=None,
    x_coordinate=None,
    y_coordinate=None,
):
    if not chapter_name or not element_idx:
        frappe.throw("Chapter Name and Element Index are required")

    element_idx = int(element_idx)
    chapter = frappe.get_doc("LMS Chapter", chapter_name)
    interactive_content = _get_interactive_video_content(chapter)

    if not interactive_content:
        frappe.throw("No Interactive Video Content found for this chapter")

    target = None
    for el in interactive_content.interactive_elements:
        if el.idx == element_idx:
            target = el
            break

    if not target:
        frappe.throw(f"Interactive element with index {element_idx} not found")

    if interaction_type_name is not None:
        target.interaction_type = interaction_type_name
    if timeline_seconds is not None:
        target.timeline_seconds = float(timeline_seconds)
    if element_text is not None:
        target.element_text = element_text
    if secondary_text is not None:
        target.secondary_text = secondary_text
    target.is_required = 1 if is_required else 0

    # Apply new fields if provided
    if end_time_seconds is not None:
        target.end_time_seconds = float(end_time_seconds) if end_time_seconds else None
    if pause_video is not None:
        target.pause_video = 1 if pause_video in (True, 1, "1", "true", "True") else 0
    if display_mode is not None:
        target.display_mode = display_mode
    if correct_action is not None:
        target.correct_action = correct_action
    if incorrect_action is not None:
        target.incorrect_action = incorrect_action
    if correct_jump_seconds is not None:
        target.correct_jump_seconds = float(correct_jump_seconds) if str(correct_jump_seconds).strip() != "" else None
    if incorrect_jump_seconds is not None:
        target.incorrect_jump_seconds = float(incorrect_jump_seconds) if str(incorrect_jump_seconds).strip() != "" else None
    if require_correct is not None:
        target.require_correct = 1 if require_correct in (True, 1, "1", "true", "True") else 0
    if feedback_correct is not None:
        target.feedback_correct = feedback_correct
    if feedback_incorrect is not None:
        target.feedback_incorrect = feedback_incorrect
    if sort_order is not None:
        target.sort_order = int(sort_order)
    
    frappe.log_error(f"UPDATE INTERACTION DEBUG: inc_action={incorrect_action}, inc_jump={incorrect_jump_seconds}", "Update Interaction Payload")

    if x_coordinate is not None:
        target.x_coordinate = float(x_coordinate) if x_coordinate else None
    if y_coordinate is not None:
        target.y_coordinate = float(y_coordinate) if y_coordinate else None

    if options and isinstance(options, str):
        options = json.loads(options)

    if target.interaction_type == "Knowledge Check":
        if target.linked_record_type == "LMS Quiz" and target.linked_record_name:
            quiz_doc = frappe.get_doc("LMS Quiz", target.linked_record_name)
            if quiz_doc.questions:
                q_link = quiz_doc.questions[0]
                q_doc = frappe.get_doc("LMS Quiz Question", q_link.quiz_question)
                if element_text is not None:
                    q_doc.question_text = element_text
                
                if options is not None:
                    q_doc.set("options", [])
                    for i, opt in enumerate(options):
                        q_doc.append("options", {
                            "option_text": opt.get("text") or f"Option {i+1}",
                            "is_correct": 1 if opt.get("isCorrect") else 0
                        })
                q_doc.save(ignore_permissions=True)
            
            if element_text is not None:
                quiz_doc.title = element_text
                quiz_doc.save(ignore_permissions=True)
        elif options:
            quiz_doc = _create_quiz_for_knowledge_check(element_text, options, is_required)
            target.linked_record_type = "LMS Quiz"
            target.linked_record_name = quiz_doc.name

    elif target.interaction_type == "Poll" and options is not None:
        target.secondary_text = json.dumps(options)

    if target.name:
        target.db_update()

    interactive_content.save(ignore_permissions=True)
    return _get_all_elements_sorted(interactive_content)


@frappe.whitelist(allow_guest=False)
def remove_interaction(chapter_name, element_idx):
    if not chapter_name or not element_idx:
        frappe.throw("Chapter Name and Element Index are required")

    element_idx = int(element_idx)
    chapter = frappe.get_doc("LMS Chapter", chapter_name)
    interactive_content = _get_interactive_video_content(chapter)

    if not interactive_content:
        frappe.throw("No Interactive Video Content found for this chapter")

    target = None
    for el in interactive_content.interactive_elements:
        if el.idx == element_idx:
            target = el
            break

    if not target:
        frappe.throw(f"Interactive element with index {element_idx} not found")

    if target.linked_record_type and target.linked_record_name:
        try:
            if frappe.db.exists(target.linked_record_type, target.linked_record_name):
                frappe.delete_doc(
                    target.linked_record_type,
                    target.linked_record_name,
                    ignore_permissions=True,
                )
        except Exception as e:
            frappe.log_error("Failed to delete linked interaction record", str(e))

    interactive_content.interactive_elements = [
        el for el in interactive_content.interactive_elements if el.idx != element_idx
    ]
    interactive_content.save(ignore_permissions=True)

    return _get_all_elements_sorted(interactive_content)


@frappe.whitelist(allow_guest=False)
def duplicate_interaction(chapter_name, element_idx):
    """Deep-clone an interaction element, including linked Quiz records.
    Clones everything except learner progress.
    """
    if not chapter_name or not element_idx:
        frappe.throw("Chapter Name and Element Index are required")

    element_idx = int(element_idx)
    chapter = frappe.get_doc("LMS Chapter", chapter_name)
    interactive_content = _get_interactive_video_content(chapter)

    if not interactive_content:
        frappe.throw("No Interactive Video Content found for this chapter")

    source = None
    for el in interactive_content.interactive_elements:
        if el.idx == element_idx:
            source = el
            break

    if not source:
        frappe.throw(f"Interactive element with index {element_idx} not found")

    # Fields to copy from the source element
    clone_fields = [
        "interaction_type", "element_text", "secondary_text",
        "x_coordinate", "y_coordinate", "is_correct", "is_required",
        "end_time_seconds", "pause_video", "display_mode",
        "correct_action", "incorrect_action",
        "correct_jump_seconds", "incorrect_jump_seconds",
        "require_correct", "feedback_correct", "feedback_incorrect",
        "sort_order",
    ]

    new_data = {}
    for field in clone_fields:
        new_data[field] = getattr(source, field, None)

    # Offset timeline by 5 seconds to avoid overlap
    new_data["timeline_seconds"] = (source.timeline_seconds or 0) + 5

    # Deep-clone linked Quiz if Knowledge Check
    if (
        source.linked_record_type == "LMS Quiz"
        and source.linked_record_name
        and frappe.db.exists("LMS Quiz", source.linked_record_name)
    ):
        old_quiz = frappe.get_doc("LMS Quiz", source.linked_record_name)

        # Clone questions and their options
        new_questions = []
        for q_link in old_quiz.questions:
            if not frappe.db.exists("LMS Quiz Question", q_link.quiz_question):
                continue

            old_q = frappe.get_doc("LMS Quiz Question", q_link.quiz_question)
            new_q = frappe.get_doc({
                "doctype": "LMS Quiz Question",
                "question_text": old_q.question_text,
                "type": old_q.type,
                "score": old_q.score,
            })
            for opt in old_q.options:
                new_q.append("options", {
                    "option_text": opt.option_text,
                    "is_correct": opt.is_correct,
                })
            new_q.insert(ignore_permissions=True)
            new_questions.append({"quiz_question": new_q.name, "order": q_link.order})

        new_quiz = frappe.get_doc({
            "doctype": "LMS Quiz",
            "title": f"{old_quiz.title} (Copy)",
            "max_attempts": old_quiz.max_attempts,
            "passing_percentage": old_quiz.passing_percentage,
        })
        for nq in new_questions:
            new_quiz.append("questions", nq)
        new_quiz.insert(ignore_permissions=True)

        new_data["linked_record_type"] = "LMS Quiz"
        new_data["linked_record_name"] = new_quiz.name
    else:
        new_data["linked_record_type"] = source.linked_record_type
        new_data["linked_record_name"] = source.linked_record_name

    interactive_content.append("interactive_elements", new_data)
    interactive_content.save(ignore_permissions=True)

    return _get_all_elements_sorted(interactive_content)
