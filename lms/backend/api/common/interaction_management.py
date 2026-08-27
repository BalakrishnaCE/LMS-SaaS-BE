import frappe
import json

@frappe.whitelist(allow_guest=False)
def get_interactions(chapter_name):
    """Get all interactive elements for a chapter, sorted by timeline_seconds."""
    if not chapter_name:
        frappe.throw("Chapter Name is required")

    chapter = frappe.get_doc("LMS Chapter", chapter_name)
    interactive_content = _get_interactive_video_content(chapter)

    if not interactive_content:
        return []

    elements = []
    for el in interactive_content.interactive_elements:
        elements.append(_serialize_element(el))

    elements.sort(key=lambda e: (e.get("sort_order") or 0, e.get("timeline_seconds") or 0))
    return elements


def _get_interactive_video_content(chapter):
    """Find the LMS Interactive Video Content linked to a chapter."""
    if not hasattr(chapter, "contents") or not chapter.contents:
        return None

    for content_link in chapter.contents:
        if content_link.content_type == "LMS Interactive Video Content":
            try:
                return frappe.get_doc(
                    "LMS Interactive Video Content", content_link.content_reference
                )
            except Exception:
                return None
    return None


def _serialize_element(el):
    """Serialize a single LMS Interactive Element child row to a dict."""
    data = {
        "name": el.name,
        "idx": el.idx,
        "interaction_type": el.interaction_type,
        "timeline_seconds": el.timeline_seconds,
        "end_time_seconds": el.end_time_seconds,
        "element_text": el.element_text,
        "secondary_text": el.secondary_text,
        "linked_record_type": el.linked_record_type,
        "linked_record_name": el.linked_record_name,
        "is_correct": el.is_correct,
        "is_required": bool(el.is_required),
        "x_coordinate": el.x_coordinate,
        "y_coordinate": el.y_coordinate,
        "pause_video": bool(el.pause_video) if el.pause_video is not None else True,
        "display_mode": el.display_mode or "immediate",
        "correct_action": el.correct_action or "continue",
        "incorrect_action": el.incorrect_action or "message",
        "correct_jump_seconds": el.correct_jump_seconds,
        "incorrect_jump_seconds": el.incorrect_jump_seconds,
        "require_correct": bool(el.require_correct),
        "feedback_correct": el.feedback_correct or "",
        "feedback_incorrect": el.feedback_incorrect or "",
        "sort_order": el.sort_order or 0,
    }

    if el.interaction_type == "Knowledge Check" and el.linked_record_type == "LMS Quiz" and el.linked_record_name:
        try:
            quiz = frappe.get_doc("LMS Quiz", el.linked_record_name)
            if quiz.questions:
                q_link = quiz.questions[0]
                q_doc = frappe.get_doc("LMS Quiz Question", q_link.quiz_question)
                
                if q_doc.question_text:
                    data["element_text"] = q_doc.question_text

                options = []
                for opt in q_doc.options:
                    options.append({
                        "text": opt.option_text,
                        "isCorrect": bool(opt.is_correct)
                    })
                data["options"] = options
        except Exception:
            pass

    return data


def _get_all_elements_sorted(interactive_content):
    """Return all elements from an interactive content doc, sorted by timeline_seconds."""
    interactive_content.reload()
    elements = [_serialize_element(el) for el in interactive_content.interactive_elements]
    elements.sort(key=lambda e: (e.get("sort_order") or 0, e.get("timeline_seconds") or 0))
    return elements


def _create_quiz_for_knowledge_check(question_text, options, is_required=False):
    """Create an LMS Quiz with a single question for a Knowledge Check interaction."""
    question_doc = frappe.get_doc(
        {
            "doctype": "LMS Quiz Question",
            "question_text": question_text or "Knowledge Check Question",
            "type": "Choices",
            "score": 1,
        }
    )

    for opt in options:
        question_doc.append(
            "options",
            {
                "option_text": opt.get("text", ""),
                "is_correct": opt.get("isCorrect", False),
            },
        )

    question_doc.insert(ignore_permissions=True)

    quiz_doc = frappe.get_doc(
        {
            "doctype": "LMS Quiz",
            "title": f"KC: {(question_text or 'Question')[:50]}",
            "max_attempts": 0 if not is_required else 1,
            "passing_percentage": 100,
        }
    )
    quiz_doc.append("questions", {"quiz_question": question_doc.name, "order": 1})
    quiz_doc.insert(ignore_permissions=True)

    return quiz_doc


def _migrate_to_interactive_video(chapter):
    """Migrate a plain LMS Video Content chapter to LMS Interactive Video Content."""
    if not hasattr(chapter, "contents") or not chapter.contents:
        return None

    old_content_link = None
    old_doc = None

    for content_link in chapter.contents:
        if content_link.content_type == "LMS Video Content":
            try:
                old_doc = frappe.get_doc("LMS Video Content", content_link.content_reference)
                old_content_link = content_link
                break
            except Exception:
                return None

    if not old_doc:
        return None

    new_doc = frappe.get_doc(
        {
            "doctype": "LMS Interactive Video Content",
            "title": old_doc.title or chapter.title,
            "base_media": getattr(old_doc, "base_media", None),
            "video_url": getattr(old_doc, "video_url", None),
            "track_progress": getattr(old_doc, "track_progress", 1),
        }
    )
    new_doc.insert(ignore_permissions=True)

    old_content_link.content_type = "LMS Interactive Video Content"
    old_content_link.content_reference = new_doc.name
    chapter.save(ignore_permissions=True)

    try:
        frappe.delete_doc("LMS Video Content", old_doc.name, ignore_permissions=True)
    except Exception as e:
        frappe.log_error("Failed to delete old video content after migration", str(e))

    return new_doc
