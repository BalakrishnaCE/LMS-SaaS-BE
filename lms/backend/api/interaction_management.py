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

    elements.sort(key=lambda e: e.get("timeline_seconds") or 0)
    return elements


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
    """Add a new interactive element to a chapter's Interactive Video Content.

    If the chapter currently uses LMS Video Content, it is migrated
    to LMS Interactive Video Content automatically.
    """
    if not chapter_name or not interaction_type_name:
        frappe.throw("Chapter Name and Interaction Type are required")

    timeline_seconds = float(timeline_seconds or 0)

    chapter = frappe.get_doc("LMS Chapter", chapter_name)
    interactive_content = _get_interactive_video_content(chapter)

    # If chapter has plain Video Content, migrate to Interactive Video Content
    if not interactive_content:
        interactive_content = _migrate_to_interactive_video(chapter)

    if not interactive_content:
        frappe.throw("Could not find or create Interactive Video Content for this chapter")

    # Parse options if passed as string
    if options and isinstance(options, str):
        options = json.loads(options)

    # Build the child row data
    element_data = {
        "interaction_type": interaction_type_name,
        "timeline_seconds": timeline_seconds,
        "element_text": element_text or "",
        "secondary_text": secondary_text or "",
        "is_required": 1 if is_required else 0,
    }

    # Handle linked records for Knowledge Check (Quiz)
    if interaction_type_name == "Knowledge Check" and options:
        quiz_doc = _create_quiz_for_knowledge_check(element_text, options, is_required)
        element_data["linked_record_type"] = "LMS Quiz"
        element_data["linked_record_name"] = quiz_doc.name

    # For Poll, store options as JSON in secondary_text
    elif interaction_type_name == "Poll" and options:
        element_data["secondary_text"] = json.dumps(options)

    # For Key Takeaway, secondary_text already holds JSON bullet points from frontend
    # For Reflection Prompt, element_text holds the prompt, secondary_text holds max_chars

    interactive_content.append("interactive_elements", element_data)
    interactive_content.save(ignore_permissions=True)

    # Return the updated list
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
    """Update an existing interactive element by its child table index."""
    if not chapter_name or not element_idx:
        frappe.throw("Chapter Name and Element Index are required")

    element_idx = int(element_idx)
    chapter = frappe.get_doc("LMS Chapter", chapter_name)
    interactive_content = _get_interactive_video_content(chapter)

    if not interactive_content:
        frappe.throw("No Interactive Video Content found for this chapter")

    # Find element by idx
    target = None
    for el in interactive_content.interactive_elements:
        if el.idx == element_idx:
            target = el
            break

    if not target:
        frappe.throw(f"Interactive element with index {element_idx} not found")

    # Update fields if provided
    if interaction_type_name is not None:
        target.interaction_type = interaction_type_name
    if timeline_seconds is not None:
        target.timeline_seconds = float(timeline_seconds)
    if element_text is not None:
        target.element_text = element_text
    if secondary_text is not None:
        target.secondary_text = secondary_text
    target.is_required = 1 if is_required else 0

    # Parse options if passed as string
    if options and isinstance(options, str):
        options = json.loads(options)

    # Handle linked records for Knowledge Check (Quiz)
    if target.interaction_type == "Knowledge Check":
        if target.linked_record_type == "LMS Quiz" and target.linked_record_name:
            quiz_doc = frappe.get_doc("LMS Quiz", target.linked_record_name)
            # Update the first (and only) question
            if quiz_doc.questions:
                q_link = quiz_doc.questions[0]
                q_doc = frappe.get_doc("LMS Quiz Question", q_link.quiz_question)
                if element_text is not None:
                    q_doc.question_text = element_text
                
                # Delete old options and add new ones if options provided
                if options is not None:
                    q_doc.set("options", [])
                    for i, opt in enumerate(options):
                        q_doc.append("options", {
                            "option_text": opt.get("text") or f"Option {i+1}",
                            "is_correct": 1 if opt.get("isCorrect") else 0
                        })
                q_doc.save(ignore_permissions=True)
            
            # Update Quiz Title
            if element_text is not None:
                quiz_doc.title = element_text
                quiz_doc.save(ignore_permissions=True)
        elif options:
            # If no quiz exists yet but options provided, create one
            quiz_doc = _create_quiz_for_knowledge_check(element_text, options, is_required)
            target.linked_record_type = "LMS Quiz"
            target.linked_record_name = quiz_doc.name

    # For Poll, update JSON in secondary_text
    elif target.interaction_type == "Poll" and options is not None:
        target.secondary_text = json.dumps(options)
        
    # For Reflection Prompt, update is_required
    elif target.interaction_type == "Reflection Prompt":
        # we still use secondary_text for max_char, is_required goes where?
        pass

    interactive_content.save(ignore_permissions=True)
    return _get_all_elements_sorted(interactive_content)


@frappe.whitelist(allow_guest=False)
def remove_interaction(chapter_name, element_idx):
    """Remove an interactive element by its child table index."""
    if not chapter_name or not element_idx:
        frappe.throw("Chapter Name and Element Index are required")

    element_idx = int(element_idx)
    chapter = frappe.get_doc("LMS Chapter", chapter_name)
    interactive_content = _get_interactive_video_content(chapter)

    if not interactive_content:
        frappe.throw("No Interactive Video Content found for this chapter")

    # Find and remove element, cascade delete linked records
    target = None
    for el in interactive_content.interactive_elements:
        if el.idx == element_idx:
            target = el
            break

    if not target:
        frappe.throw(f"Interactive element with index {element_idx} not found")

    # Cascade delete linked record if exists
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


# ── Private Helpers ────────────────────────────────────────────────────────


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


def _migrate_to_interactive_video(chapter):
    """Migrate a plain LMS Video Content chapter to LMS Interactive Video Content.

    Copies base_media/video_url from the old video doc, creates the new
    interactive doc, updates the chapter content link, and deletes the old doc.
    """
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

    # Create new Interactive Video Content with copied media
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

    # Update the chapter content link to point to the new doc
    old_content_link.content_type = "LMS Interactive Video Content"
    old_content_link.content_reference = new_doc.name
    chapter.save(ignore_permissions=True)

    # Delete the old video content doc
    try:
        frappe.delete_doc("LMS Video Content", old_doc.name, ignore_permissions=True)
    except Exception as e:
        frappe.log_error("Failed to delete old video content after migration", str(e))

    return new_doc


def _create_quiz_for_knowledge_check(question_text, options, is_required=False):
    """Create an LMS Quiz with a single question for a Knowledge Check interaction."""
    # Create the quiz question first
    question_doc = frappe.get_doc(
        {
            "doctype": "LMS Quiz Question",
            "question_text": question_text or "Knowledge Check Question",
            "type": "Choices",
            "score": 1,
        }
    )

    # Add options
    for opt in options:
        question_doc.append(
            "options",
            {
                "option_text": opt.get("text", ""),
                "is_correct": opt.get("isCorrect", False),
            },
        )

    question_doc.insert(ignore_permissions=True)

    # Create the quiz
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


def _serialize_element(el):
    """Serialize a single LMS Interactive Element child row to a dict."""
    data = {
        "idx": el.idx,
        "interaction_type": el.interaction_type,
        "timeline_seconds": el.timeline_seconds,
        "element_text": el.element_text,
        "secondary_text": el.secondary_text,
        "linked_record_type": el.linked_record_type,
        "linked_record_name": el.linked_record_name,
        "is_correct": el.is_correct,
        "is_required": bool(el.is_required),
        "x_coordinate": el.x_coordinate,
        "y_coordinate": el.y_coordinate,
    }

    if el.interaction_type == "Knowledge Check" and el.linked_record_type == "LMS Quiz" and el.linked_record_name:
        try:
            quiz = frappe.get_doc("LMS Quiz", el.linked_record_name)
            if quiz.questions:
                q_link = quiz.questions[0]
                q_doc = frappe.get_doc("LMS Quiz Question", q_link.quiz_question)
                
                # Fetch question text directly from the linked quiz question
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
    elements.sort(key=lambda e: e.get("timeline_seconds") or 0)
    return elements
