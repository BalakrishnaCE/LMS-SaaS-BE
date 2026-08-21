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

    element_data = {
        "interaction_type": interaction_type_name,
        "timeline_seconds": timeline_seconds,
        "element_text": element_text or "",
        "secondary_text": secondary_text or "",
        "is_required": 1 if is_required else 0,
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
