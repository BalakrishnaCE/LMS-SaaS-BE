import frappe
from frappe.utils import now

@frappe.whitelist(allow_guest=False)
def get_curriculum(module_name):
    if not module_name:
        frappe.throw("Module Name is required")
        
    module = frappe.get_doc("LMS Module", module_name)
    
    curriculum = []
    
    for ml in module.lessons:
        lesson = frappe.get_doc("LMS Lesson", ml.lesson)
        chapters = []
        for ch in lesson.chapters:
            chapter = frappe.get_doc("LMS Chapter", ch.chapter)
            
            chapter_contents = []
            
            if hasattr(chapter, "contents") and chapter.contents:
                # Sort contents by 'order' if available and > 0, fallback to a high number so unordered items go last
                sorted_contents = sorted(chapter.contents, key=lambda x: (x.order or 999, x.idx))
                for content_link in sorted_contents:
                    raw_type = content_link.content_type
                    reverse_map = {
                        'LMS Text Content': 'text',
                        'LMS Video Content': 'video',
                        'LMS Audio Content': 'audio',
                        'LMS Presentation Content': 'presentation',
                        'LMS Document Content': 'file',
                        'LMS Quiz Content': 'quiz',
                        'LMS Assessment Content': 'assessment',
                        'LMS Iframe Content': 'iframe',
                        'LMS Interactive Video Content': 'interactive_video',
                        'LMS Flashcard Content': 'flashcard',
                        'LMS Image Content': 'image',
                    }
                    content_type = reverse_map.get(raw_type, 'document')
                    
                    try:
                        content_doc = frappe.get_doc(raw_type, content_link.content_reference)
                        content_data = content_doc.as_dict()
                        
                        # Convert datetimes to strings to prevent json serialization errors
                        if 'creation' in content_data:
                            content_data['creation'] = str(content_data['creation'])
                        if 'modified' in content_data:
                            content_data['modified'] = str(content_data['modified'])
                            
                        # Recursively fetch Quiz data for frontend builder
                        quiz_field = None
                        if raw_type == 'LMS Quiz Content' and content_doc.quiz:
                            quiz_field = content_doc.quiz
                        elif raw_type == 'LMS Assessment Content' and content_doc.assessment:
                            quiz_field = content_doc.assessment
                            
                        if quiz_field:
                            quiz_doc = frappe.get_doc("LMS Quiz", quiz_field)
                            quiz_data = quiz_doc.as_dict()
                            quiz_data['questions'] = []
                            
                            for ch_q in quiz_doc.questions:
                                q_doc = frappe.get_doc("LMS Quiz Question", ch_q.quiz_question)
                                q_data = q_doc.as_dict()
                                q_data['options'] = []
                                for opt in q_doc.options:
                                    q_data['options'].append(opt.as_dict())
                                quiz_data['questions'].append(q_data)
                                
                            content_data['quiz_data'] = quiz_data

                        # Serialize interactive_elements child table for Interactive Video and Image Hotspots
                        if raw_type in ('LMS Interactive Video Content', 'LMS Image Content') and hasattr(content_doc, 'interactive_elements'):
                            from lms.backend.api.common.interaction_management import _serialize_element
                            elements = []
                            for el in content_doc.interactive_elements:
                                elements.append(_serialize_element(el))
                            content_data['interactive_elements'] = elements

                    except Exception as e:
                        frappe.log_error(f"Error fetching {raw_type}", str(e))
                        content_data = None
                        
                    if raw_type != 'LMS Flashcard Content':
                        chapter_contents.append({
                            "id": content_link.content_reference,
                            "contentType": content_type,
                            "contentData": content_data
                        })

            flashcards = []
            if hasattr(chapter, "contents") and chapter.contents:
                for content_link in chapter.contents:
                    if content_link.content_type == "LMS Flashcard Content":
                        try:
                            fc_doc = frappe.get_doc("LMS Flashcard Content", content_link.content_reference)
                            if hasattr(fc_doc, "interactive_elements"):
                                for el in fc_doc.interactive_elements:
                                    flashcards.append({
                                        "id": str(el.name or el.idx),
                                        "front": el.element_text,
                                        "back": el.secondary_text
                                    })
                        except Exception as e:
                            pass
                        break

            chapters.append({
                "name": chapter.name,
                "title": chapter.title,
                "scoring": chapter.scoring,
                "order": ch.order,
                "contents": chapter_contents,
                "flashcards": flashcards
            })
        
        curriculum.append({
            "name": lesson.name,
            "lesson_name": lesson.lesson_name,
            "description": lesson.description,
            "order": ml.order,
            "chapters": chapters
        })
        
    return curriculum

@frappe.whitelist(allow_guest=False)
def add_lesson(module_name, lesson_name, description=""):
    if not module_name or not lesson_name:
        frappe.throw("Module Name and Lesson Name are required")
        
    # Check if lesson exists, else create it
    if not frappe.db.exists("LMS Lesson", {"lesson_name": lesson_name}):
        lesson = frappe.get_doc({
            "doctype": "LMS Lesson",
            "lesson_name": lesson_name,
            "description": description
        })
        lesson.insert(ignore_permissions=True)
    else:
        lesson = frappe.get_doc("LMS Lesson", {"lesson_name": lesson_name})
        
    # Attach to module
    module = frappe.get_doc("LMS Module", module_name)
    
    # Check if already attached
    for ml in module.lessons:
        if ml.lesson == lesson.name:
            return {"status": "already_exists", "lesson": lesson.name}
            
    module.append("lessons", {
        "lesson": lesson.name,
        "order": len(module.lessons) + 1
    })
    module.save(ignore_permissions=True)
    
    return {"status": "success", "lesson": lesson.name}

import json

@frappe.whitelist(allow_guest=False)
def add_chapter(lesson_name, chapter_title, content_type="document", content_data=None):
    try:
        frappe.log_error("add_chapter API called", f"Lesson: {lesson_name}, Title: {chapter_title}, Type: {content_type}, Data: {content_data}")
        if not lesson_name or not chapter_title:
            frappe.throw("Lesson Name and Chapter Title are required")
            
        type_map = {
            'text': 'LMS Text Content',
            'file': 'LMS Document Content',
            'video': 'LMS Video Content',
            'audio': 'LMS Audio Content',
            'presentation': 'LMS Presentation Content', # Maps to base_media (File upload)
            'quiz': 'LMS Quiz Content', 
            'iframe': 'LMS Iframe Content',
            'assessment': 'LMS Assessment Content',
            'ai': 'LMS Text Content',
            'interactive_video': 'LMS Interactive Video Content'
        }
        doctype_name = type_map.get(content_type, 'LMS Text Content')
            
        # Always create a new chapter
        chapter = frappe.get_doc({
            "doctype": "LMS Chapter",
            "title": chapter_title,
            "scoring": 0
        })
        chapter.insert(ignore_permissions=True)
        # Only create content if content_type is provided and not 'none'
        if content_type and content_type.lower() != 'none':
            try:
                # Create the content record to link
                content_doc = frappe.get_doc({
                    "doctype": doctype_name,
                    "title": chapter_title
                })
                
                # Inject dynamic fields from frontend
                if content_data:
                    if isinstance(content_data, str):
                        content_data = json.loads(content_data)
                    for key, value in content_data.items():
                        if value is not None:
                            content_doc.set(key, value)
                
                content_doc.insert(ignore_permissions=True, ignore_mandatory=True)
                
                chapter.append("contents", {
                    "content_type": doctype_name,
                    "content_reference": content_doc.name,
                    "order": 1
                })
                chapter.save(ignore_permissions=True)
            except Exception as inner_e:
                frappe.log_error("Failed to create content doc", str(inner_e))
                pass # If content creation fails due to strict validations, we still have the Chapter
                
        lesson = frappe.get_doc("LMS Lesson", lesson_name)
        
        # Check if attached (in rare cases of identical IDs)
        for ch in lesson.chapters:
            if ch.chapter == chapter.name:
                return {"status": "already_exists", "chapter": chapter.name}
                
        lesson.append("chapters", {
            "chapter": chapter.name,
            "order": len(lesson.chapters) + 1
        })
        lesson.save(ignore_permissions=True)
        
        return {"status": "success", "chapter": chapter.name}
        
    except Exception as e:
        import traceback
        frappe.log_error("add_chapter FATAL ERROR", traceback.format_exc())
        raise

@frappe.whitelist(allow_guest=False)
def add_content_block(chapter_name, content_type, title=None, content_data=None):
    try:
        if not chapter_name or not content_type:
            frappe.throw("Chapter Name and Content Type are required")
            
        type_map = {
            'text': 'LMS Text Content',
            'file': 'LMS Document Content',
            'video': 'LMS Video Content',
            'audio': 'LMS Audio Content',
            'presentation': 'LMS Presentation Content',
            'quiz': 'LMS Quiz Content', 
            'iframe': 'LMS Iframe Content',
            'assessment': 'LMS Assessment Content',
            'ai': 'LMS Text Content',
            'interactive_video': 'LMS Interactive Video Content',
            'image': 'LMS Image Content',
        }
        doctype_name = type_map.get(content_type, 'LMS Text Content')
        
        chapter = frappe.get_doc("LMS Chapter", chapter_name)
        
        # Create the content record to link
        content_doc = frappe.get_doc({
            "doctype": doctype_name,
            "title": title or chapter.title or "Untitled Content"
        })
        
        quiz_data = None
        # Inject dynamic fields from frontend
        if content_data:
            if isinstance(content_data, str):
                content_data = json.loads(content_data)
            quiz_data = content_data.pop("quiz_data", None)
            for key, value in content_data.items():
                if value is not None:
                    content_doc.set(key, value)
        
        content_doc.insert(ignore_permissions=True, ignore_mandatory=True)
        
        new_order = len(chapter.contents) + 1
        
        chapter.append("contents", {
            "content_type": doctype_name,
            "content_reference": content_doc.name,
            "order": new_order
        })
        chapter.save(ignore_permissions=True)
        
        if quiz_data and doctype_name in ["LMS Quiz Content", "LMS Assessment Content"]:
            chapter.reload()
            sorted_contents = sorted(chapter.contents, key=lambda x: (x.order or 999, x.idx))
            for idx, content in enumerate(sorted_contents):
                if content.content_reference == content_doc.name:
                    save_chapter_quiz(chapter_name, quiz_data, idx)
                    break
                    
        return {"status": "success", "content_reference": content_doc.name, "doctype": doctype_name}
    except Exception as e:
        import traceback
        frappe.log_error("add_content_block ERROR", traceback.format_exc())
        raise

@frappe.whitelist(allow_guest=False)
def remove_content_block(chapter_name, content_reference):
    try:
        if not chapter_name or not content_reference:
            frappe.throw("Chapter Name and Content Reference are required")
            
        chapter = frappe.get_doc("LMS Chapter", chapter_name)
        target_row = None
        
        for row in chapter.contents:
            if row.content_reference == content_reference:
                target_row = row
                break
                
        if target_row:
            chapter.remove(target_row)
            chapter.save(ignore_permissions=True)
            
            # Also try to delete the actual content document
            try:
                if frappe.db.exists(target_row.content_type, target_row.content_reference):
                    frappe.delete_doc(target_row.content_type, target_row.content_reference, ignore_permissions=True)
            except Exception as inner_e:
                frappe.log_error("Failed to delete content doc on remove_content_block", str(inner_e))
                pass
                
        return {"status": "success"}
    except Exception as e:
        import traceback
        frappe.log_error("remove_content_block ERROR", traceback.format_exc())
        raise

@frappe.whitelist(allow_guest=False)
def reorder_content_blocks(chapter_name, ordered_references):
    """
    ordered_references: A JSON string or list of content_reference IDs in the new order.
    """
    try:
        if not chapter_name or not ordered_references:
            frappe.throw("Chapter Name and Ordered References are required")
            
        if isinstance(ordered_references, str):
            ordered_references = json.loads(ordered_references)
            
        chapter = frappe.get_doc("LMS Chapter", chapter_name)
        
        # Update the order of the contents based on the index in ordered_references
        ref_order_map = {ref: idx + 1 for idx, ref in enumerate(ordered_references)}
        
        for row in chapter.contents:
            if row.content_reference in ref_order_map:
                row.order = ref_order_map[row.content_reference]
                
        chapter.save(ignore_permissions=True)
        return {"status": "success"}
    except Exception as e:
        import traceback
        frappe.log_error("reorder_content_blocks ERROR", traceback.format_exc())
        raise

@frappe.whitelist(allow_guest=False)
def remove_lesson(module_name, lesson_name):
    module = frappe.get_doc("LMS Module", module_name)
    module.lessons = [ml for ml in module.lessons if ml.lesson != lesson_name]
    module.save(ignore_permissions=True)
    
    if frappe.db.exists("LMS Lesson", lesson_name):
        lesson = frappe.get_doc("LMS Lesson", lesson_name)
        if hasattr(lesson, "chapters"):
            for ch in lesson.chapters:
                remove_chapter(lesson_name, ch.chapter)
        frappe.delete_doc("LMS Lesson", lesson_name, ignore_permissions=True)
        
    return {"status": "success"}

@frappe.whitelist(allow_guest=False)
def remove_chapter(lesson_name, chapter_name):
    if frappe.db.exists("LMS Lesson", lesson_name):
        lesson = frappe.get_doc("LMS Lesson", lesson_name)
        lesson.chapters = [ch for ch in lesson.chapters if ch.chapter != chapter_name]
        lesson.save(ignore_permissions=True)
    
    if frappe.db.exists("LMS Chapter", chapter_name):
        chapter = frappe.get_doc("LMS Chapter", chapter_name)
        
        # Gather content references before deleting the chapter to avoid LinkExistsError
        contents_to_delete = []
        if hasattr(chapter, "contents"):
            for content in chapter.contents:
                if content.content_type and content.content_reference:
                    contents_to_delete.append((content.content_type, content.content_reference))
        
        # Delete the chapter first so the links are removed
        frappe.delete_doc("LMS Chapter", chapter_name, ignore_permissions=True)
        
        # Now safely delete the orphaned content records
        for ctype, crefe in contents_to_delete:
            if frappe.db.exists(ctype, crefe):
                frappe.delete_doc(ctype, crefe, ignore_permissions=True)
        
    return {"status": "success"}

@frappe.whitelist(allow_guest=False)
def get_admin_dashboard_modules():
    modules = frappe.get_all("LMS Module", 
        fields=["name", "module_name", "category", "status", "creation", "modified", "image", "is_mandatory", "duration"],
        order_by="creation desc"
    )
    
    for mod in modules:
        # Get total assigned learners who started
        total = frappe.db.count("LMS Module Tracker", {"module": mod.name})
        completed = frappe.db.count("LMS Module Tracker", {"module": mod.name, "status": "Completed"})
        
        # Get lesson count using SQL to avoid any child table ORM quirks
        lesson_count_res = frappe.db.sql("""
            SELECT count(name) 
            FROM `tabLMS Module Lesson Child` 
            WHERE parent = %s AND parenttype = 'LMS Module'
        """, (mod.name,))
        lesson_count = lesson_count_res[0][0] if lesson_count_res else 0
        
        mod.totalLearners = total
        mod.completedLearners = completed
        mod.completionRate = (completed / total * 100) if total > 0 else 0
        mod.lesson_count = lesson_count
        
    return modules

@frappe.whitelist(allow_guest=False)
def delete_module(module_name):
    if not module_name:
        frappe.throw("Module Name is required")
        
    if frappe.db.exists("LMS Module", module_name):
        frappe.delete_doc("LMS Module", module_name, ignore_permissions=True)
        return {"status": "success"}
    return {"status": "not_found"}

@frappe.whitelist(allow_guest=False)
def duplicate_module(module_name):
    if not module_name:
        frappe.throw("Module Name is required")
        
    original = frappe.get_doc("LMS Module", module_name)
    
    # Generate unique name
    base_name = f"{original.module_name} (Copy)"
    new_name = base_name
    counter = 1
    
    while frappe.db.exists("LMS Module", new_name):
        new_name = f"{base_name} {counter}"
        counter += 1
        
    # Create copy
    new_module = frappe.copy_doc(original)
    
    base_name = f"{original.module_name} (Copy)"
    new_name = base_name
    count = 1
    
    while frappe.db.exists("LMS Module", new_name):
        new_name = f"{base_name} {count}"
        count += 1
        
    new_module.module_name = new_name
    new_module.status = "Draft"
    new_module.insert(ignore_permissions=True)
    
    return {"status": "success", "new_module_id": new_module.name}

@frappe.whitelist(allow_guest=False)
def save_chapter_quiz(chapter_name, quiz_data, content_idx=0):
    import json
    if not chapter_name or not quiz_data:
        frappe.throw("Chapter Name and Quiz Data are required")
        
    if isinstance(quiz_data, str):
        quiz_data = json.loads(quiz_data)
        
    chapter = frappe.get_doc("LMS Chapter", chapter_name)
    if not hasattr(chapter, "contents") or not chapter.contents:
        frappe.throw("Chapter has no contents")
        
    content_idx = int(content_idx)
    sorted_contents = sorted(chapter.contents, key=lambda x: (x.order or 999, x.idx))
    if content_idx >= len(sorted_contents):
        frappe.throw(f"Chapter has no content at index {content_idx}")
        
    content_link = sorted_contents[content_idx]
    if content_link.content_type not in ["LMS Quiz Content", "LMS Assessment Content"]:
        frappe.throw("Chapter is not linked to a Quiz or Assessment Content")
        
    quiz_content = frappe.get_doc(content_link.content_type, content_link.content_reference)
    
    # Check if quiz exists, else create new
    quiz_field = "quiz" if content_link.content_type == "LMS Quiz Content" else "assessment"
    
    if quiz_content.get(quiz_field):
        quiz = frappe.get_doc("LMS Quiz", quiz_content.get(quiz_field))
    else:
        quiz = frappe.new_doc("LMS Quiz")
        
    quiz.title = quiz_data.get("title") or quiz_content.title or chapter.title or "Untitled Quiz"
    quiz.description = quiz_data.get("description") or ""
    quiz.total_score = quiz_data.get("total_score", 0)
    quiz.randomize_questions = quiz_data.get("randomize_questions", 0)
    quiz.time_limit_mins = quiz_data.get("time_limit_mins", 0)
    quiz.is_passing_required = quiz_data.get("is_passing_required", 0)
    quiz.passing_percentage = quiz_data.get("passing_percentage", 0)
    quiz.instructions = quiz_data.get("instructions") or ""
    quiz.max_attempts = quiz_data.get("max_attempts", 0)
    
    # We will clear existing questions in the quiz and re-append them 
    # to handle ordering and updates simply in one pass
    quiz.set("questions", [])
    
    for idx, q_data in enumerate(quiz_data.get("questions", [])):
        q_text = (q_data.get("question_text") or "").strip()
        if not q_text:
            continue
            
        if q_data.get("name"):
            q_doc = frappe.get_doc("LMS Quiz Question", q_data.get("name"))
        else:
            q_doc = frappe.new_doc("LMS Quiz Question")
            
        q_doc.question_text = q_text
        q_doc.question_type = q_data.get("question_type", "Single Choice")
        q_doc.score = q_data.get("score", 1)
        q_doc.is_mandatory = q_data.get("is_mandatory", 1)
        q_doc.explanation = q_data.get("explanation") or ""
        
        q_doc.set("options", [])
        for opt in q_data.get("options", []):
            opt_text = (opt.get("option_text") or "").strip()
            if not opt_text:
                continue
            q_doc.append("options", {
                "option_text": opt_text,
                "is_correct": opt.get("is_correct", 0)
            })
            
        q_doc.save(ignore_permissions=True)
        
        quiz.append("questions", {
            "quiz_question": q_doc.name,
            "order": idx + 1
        })
        
    quiz.save(ignore_permissions=True)
    
    # Link back
    if not quiz_content.get(quiz_field):
        quiz_content.db_set(quiz_field, quiz.name)
        quiz_content.save(ignore_permissions=True)
        
    return {"status": "success", "message": "Quiz saved successfully", "quiz_id": quiz.name}


@frappe.whitelist(allow_guest=False)
def update_chapter_media(chapter_name, base_media=None, video_url=None, iframe_url=None, slides_json=None, content_idx=0):
    if not chapter_name:
        frappe.throw("Chapter Name is required")
        
    chapter = frappe.get_doc("LMS Chapter", chapter_name)
    if not hasattr(chapter, "contents") or not chapter.contents:
        frappe.throw("Chapter has no contents")
        
    content_idx = int(content_idx)
    sorted_contents = sorted(chapter.contents, key=lambda x: (x.order or 999, x.idx))
    if content_idx >= len(sorted_contents):
        frappe.throw(f"Chapter has no content at index {content_idx}")
        
    content_link = sorted_contents[content_idx]
    content_doc = frappe.get_doc(content_link.content_type, content_link.content_reference)
    
    if base_media is not None and hasattr(content_doc, "base_media"):
        content_doc.base_media = base_media
    if video_url is not None and hasattr(content_doc, "video_url"):
        content_doc.video_url = video_url
    if iframe_url is not None and hasattr(content_doc, "iframe_url"):
        content_doc.iframe_url = iframe_url
    if slides_json is not None and hasattr(content_doc, "slides_json"):
        content_doc.slides_json = slides_json
        if hasattr(content_doc, "source_type"):
            content_doc.source_type = "Native"
        
    content_doc.save(ignore_permissions=True)
    return {"status": "success"}

@frappe.whitelist(allow_guest=False)
def update_chapter_text(chapter_name, text_block, content_idx=0):
    try:
        content_idx = int(content_idx)
        chapter = frappe.get_doc("LMS Chapter", chapter_name)
        if not chapter.contents:
            frappe.throw("Content not found")
            
        sorted_contents = sorted(chapter.contents, key=lambda x: (x.order or 999, x.idx))
        if len(sorted_contents) <= content_idx:
            frappe.throw("Content not found")
            
        content_ref = sorted_contents[content_idx]
        if content_ref.content_type not in ["LMS Text Content", "LMS AI Content"]:
            frappe.throw(f"Content type {content_ref.content_type} does not support text updates")
            
        content_doc = frappe.get_doc(content_ref.content_type, content_ref.content_reference)
        content_doc.text_block = text_block
        content_doc.save(ignore_permissions=True)
        
        return {"status": "success"}
    except Exception as e:
        frappe.log_error("Failed to update chapter text", str(e))
        frappe.throw(str(e))


@frappe.whitelist(allow_guest=False)
def reorder_lessons(module_name, lesson_order):
    """
    Reorder lessons within a module.
    lesson_order: JSON array of lesson names in the new order.
    """
    import json as _json
    try:
        order = _json.loads(lesson_order) if isinstance(lesson_order, str) else lesson_order
        module = frappe.get_doc("LMS Module", module_name)
        # Build a lookup: lesson name -> row
        row_map = {row.lesson: row for row in module.lessons}
        # Re-assign order field and rebuild the child table in the given order
        module.lessons = []
        for idx, lesson_name in enumerate(order):
            if lesson_name in row_map:
                row = row_map[lesson_name]
                row.order = idx + 1
                module.lessons.append(row)
        module.save(ignore_permissions=True)
        return {"status": "success"}
    except Exception as e:
        frappe.log_error("reorder_lessons failed", str(e))
        frappe.throw(str(e))


@frappe.whitelist(allow_guest=False)
def reorder_chapters(lesson_name, chapter_order):
    """
    Reorder chapters within a lesson, allowing for newly moved chapters.
    chapter_order: JSON array of chapter names in the new order.
    """
    import json as _json
    try:
        order = _json.loads(chapter_order) if isinstance(chapter_order, str) else chapter_order
        lesson = frappe.get_doc("LMS Lesson", lesson_name)
        row_map = {row.chapter: row for row in lesson.chapters}
        lesson.chapters = []
        for idx, chapter_name in enumerate(order):
            if chapter_name in row_map:
                row = row_map[chapter_name]
                row.order = idx + 1
                lesson.chapters.append(row)
            else:
                row = lesson.append("chapters", {})
                row.chapter = chapter_name
                row.order = idx + 1
        lesson.save(ignore_permissions=True)
        return {"status": "success"}
    except Exception as e:
        frappe.log_error("reorder_chapters failed", str(e))
        frappe.throw(str(e))


@frappe.whitelist()
def toggle_module_archive(module_name):
    module = frappe.get_doc("LMS Module", module_name)
    if module.status == "Archived":
        # Unarchive
        last_status = module.custom_pre_archive_status or "Draft"
        if last_status == "Archived":
            last_status = "Draft"
        module.status = last_status
        module.custom_pre_archive_status = None
    else:
        # Archive
        module.custom_pre_archive_status = module.status
        module.status = "Archived"
        
    module.save(ignore_permissions=True)
    return module.status

@frappe.whitelist(allow_guest=False)
def get_teams():
    teams = frappe.get_all("LMS Team", fields=["name", "team_name"])
    for team in teams:
        learner_count = frappe.db.count("LMS Team Member", {"parent": team.name, "parenttype": "LMS Team"})
        team.learner_count = learner_count
    return teams
