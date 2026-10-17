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
                                
                                # Separate options and criteria (for Scenario Based)
                                is_scenario = q_doc.question_type == "Scenario Based"
                                q_data['options'] = []
                                q_data['criteria'] = []
                                
                                for opt in q_doc.options:
                                    opt_dict = opt.as_dict()
                                    # Skip blank options (defensive cleanup)
                                    if not (opt_dict.get('option_text') or '').strip():
                                        continue
                                    if is_scenario:
                                        # Map options → criteria for Scenario Based questions
                                        q_data['criteria'].append({
                                            'name': opt_dict.get('option_text', ''),
                                            'score': float(opt_dict.get('score') or 5)
                                        })
                                    else:
                                        q_data['options'].append(opt_dict)
                                        
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
                                        "back": el.secondary_text,
                                        "content_id": content_link.content_reference
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
        
    # Always create a new lesson so it gets a unique ID
    lesson = frappe.get_doc({
        "doctype": "LMS Lesson",
        "lesson_name": lesson_name,
        "description": description
    })
    lesson.insert(ignore_permissions=True)
        
    # Check if already attached
    if frappe.db.exists("LMS Module Lesson Child", {"parent": module_name, "lesson": lesson.name}):
        return {"status": "already_exists", "lesson": lesson.name}
        
    current_count = frappe.db.count("LMS Module Lesson Child", {"parent": module_name})
    
    frappe.get_doc({
        "doctype": "LMS Module Lesson Child",
        "parent": module_name,
        "parenttype": "LMS Module",
        "parentfield": "lessons",
        "lesson": lesson.name,
        "order": current_count + 1,
        "idx": current_count + 1
    }).insert(ignore_permissions=True)
    
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
                
                frappe.get_doc({
                    "doctype": "LMS Chapter Content",
                    "parent": chapter.name,
                    "parenttype": "LMS Chapter",
                    "parentfield": "contents",
                    "content_type": doctype_name,
                    "content_reference": content_doc.name,
                    "order": 1,
                    "idx": 1
                }).insert(ignore_permissions=True)
            except Exception as inner_e:
                frappe.log_error("Failed to create content doc", str(inner_e))
                pass # If content creation fails due to strict validations, we still have the Chapter
                
        # Check if already attached
        if frappe.db.exists("LMS Lesson Chapter", {"parent": lesson_name, "chapter": chapter.name}):
            return {"status": "already_exists", "chapter": chapter.name}
            
        current_count = frappe.db.count("LMS Lesson Chapter", {"parent": lesson_name})
        
        frappe.get_doc({
            "doctype": "LMS Lesson Chapter",
            "parent": lesson_name,
            "parenttype": "LMS Lesson",
            "parentfield": "chapters",
            "chapter": chapter.name,
            "order": current_count + 1,
            "idx": current_count + 1
        }).insert(ignore_permissions=True)
        
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
        
        current_count = frappe.db.count("LMS Chapter Content", {"parent": chapter_name})
        new_order = current_count + 1
        
        frappe.get_doc({
            "doctype": "LMS Chapter Content",
            "parent": chapter_name,
            "parenttype": "LMS Chapter",
            "parentfield": "contents",
            "content_type": doctype_name,
            "content_reference": content_doc.name,
            "order": new_order,
            "idx": new_order
        }).insert(ignore_permissions=True)
        
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

ALLOWED_CONTENT_DOCTYPES = {
    'LMS Text Content',
    'LMS Document Content',
    'LMS Video Content',
    'LMS Audio Content',
    'LMS Presentation Content',
    'LMS Quiz Content',
    'LMS Iframe Content',
    'LMS Assessment Content',
    'LMS Interactive Video Content',
    'LMS Quiz'
}

def _delete_content_record_sql(content_type, content_reference):
    """Direct SQL deletion of content records and child tables without triggering Frappe doc events."""
    if not content_type or not content_reference or content_type not in ALLOWED_CONTENT_DOCTYPES:
        return

    try:
        linked_quiz = None
        if content_type == "LMS Quiz Content":
            linked_quiz = frappe.db.get_value("LMS Quiz Content", content_reference, "quiz")
        elif content_type == "LMS Assessment Content":
            linked_quiz = frappe.db.get_value("LMS Assessment Content", content_reference, "assessment")
        elif content_type == "LMS Quiz":
            linked_quiz = content_reference

        frappe.db.sql(f"DELETE FROM `tab{content_type}` WHERE `name` = %s", (content_reference,))
        frappe.db.sql("DELETE FROM `tabLMS Content Progress` WHERE `content_reference` = %s", (content_reference,))

        if linked_quiz:
            qc_used = frappe.db.sql("SELECT name FROM `tabLMS Quiz Content` WHERE `quiz` = %s", (linked_quiz,))
            ac_used = frappe.db.sql("SELECT name FROM `tabLMS Assessment Content` WHERE `assessment` = %s", (linked_quiz,))
            if not qc_used and not ac_used:
                frappe.db.sql("DELETE FROM `tabLMS Quiz Child` WHERE `parent` = %s", (linked_quiz,))
                frappe.db.sql("DELETE FROM `tabLMS Quiz` WHERE `name` = %s", (linked_quiz,))
    except Exception as e:
        frappe.log_error("Failed to delete content record via SQL", str(e))

@frappe.whitelist(allow_guest=False)
def remove_content_block(chapter_name, content_reference):
    try:
        if not chapter_name or not content_reference:
            frappe.throw("Chapter Name and Content Reference are required")
            
        content_type = frappe.db.get_value("LMS Chapter Content", {"parent": chapter_name, "content_reference": content_reference}, "content_type")
        
        frappe.db.sql("""
            DELETE FROM `tabLMS Chapter Content`
            WHERE `parent` = %s AND `content_reference` = %s
        """, (chapter_name, content_reference))
        
        if content_type:
            _delete_content_record_sql(content_type, content_reference)
            
        frappe.db.commit()
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
            
        # Update the order of the contents based on the index in ordered_references
        ref_order_map = {ref: idx + 1 for idx, ref in enumerate(ordered_references)}
        
        for ref, order in ref_order_map.items():
            frappe.db.sql("""
                UPDATE `tabLMS Chapter Content`
                SET `order` = %s, `idx` = %s
                WHERE `parent` = %s AND `content_reference` = %s
            """, (order, order, chapter_name, ref))
            
        frappe.db.commit()
        return {"status": "success"}
    except Exception as e:
        import traceback
        frappe.log_error("reorder_content_blocks ERROR", traceback.format_exc())
        raise

@frappe.whitelist(allow_guest=False)
def rename_lesson(lesson_name, new_title, new_description=None):
    """Rename an existing LMS Lesson's title and optionally its description."""
    if not lesson_name or not new_title or not new_title.strip():
        frappe.throw("Lesson ID and new title are required")

    if not frappe.db.exists("LMS Lesson", lesson_name):
        frappe.throw(f"Lesson '{lesson_name}' not found")

    if not frappe.has_permission("LMS Lesson", "write", lesson_name):
        frappe.throw("Not permitted to edit this lesson", frappe.PermissionError)

    new_title = new_title.strip()
    updates = {"lesson_name": new_title}
    if new_description is not None:
        updates["description"] = new_description
        
    frappe.db.set_value("LMS Lesson", lesson_name, updates)

    return {"status": "success", "lesson_name": lesson_name, "title": new_title}


@frappe.whitelist(allow_guest=False)
def rename_chapter(chapter_name, new_title):
    """Rename an existing LMS Chapter's title."""
    if not chapter_name or not new_title or not new_title.strip():
        frappe.throw("Chapter ID and new title are required")

    if not frappe.db.exists("LMS Chapter", chapter_name):
        frappe.throw(f"Chapter '{chapter_name}' not found")

    if not frappe.has_permission("LMS Chapter", "write", chapter_name):
        frappe.throw("Not permitted to edit this chapter", frappe.PermissionError)

    new_title = new_title.strip()
    frappe.db.set_value("LMS Chapter", chapter_name, "title", new_title)

    return {"status": "success", "chapter_name": chapter_name, "title": new_title}


@frappe.whitelist(allow_guest=False)
def remove_lesson(module_name, lesson_name):
    frappe.db.sql("""
        DELETE FROM `tabLMS Module Lesson Child`
        WHERE `parent` = %s AND `lesson` = %s
    """, (module_name, lesson_name))
    
    other_modules = frappe.db.sql("""
        SELECT parent FROM `tabLMS Module Lesson Child`
        WHERE `lesson` = %s AND `parent` != %s
    """, (lesson_name, module_name))
    
    if not other_modules:
        chapter_names = frappe.db.sql("""
            SELECT chapter FROM `tabLMS Lesson Chapter` WHERE `parent` = %s
        """, (lesson_name,), pluck="chapter")
        for ch in chapter_names:
            remove_chapter(lesson_name, ch)
        frappe.db.sql("DELETE FROM `tabLMS Lesson Chapter` WHERE `parent` = %s", (lesson_name,))
        frappe.db.sql("DELETE FROM `tabLMS Lesson Progress` WHERE `lesson` = %s", (lesson_name,))
        frappe.db.sql("DELETE FROM `tabLMS Lesson` WHERE `name` = %s", (lesson_name,))
        
    frappe.db.commit()
    return {"status": "success"}

@frappe.whitelist(allow_guest=False)
def remove_chapter(lesson_name, chapter_name):
    frappe.db.sql("""
        DELETE FROM `tabLMS Lesson Chapter`
        WHERE `parent` = %s AND `chapter` = %s
    """, (lesson_name, chapter_name))
    
    other_lessons = frappe.db.sql("""
        SELECT parent FROM `tabLMS Lesson Chapter`
        WHERE `chapter` = %s AND `parent` != %s
    """, (chapter_name, lesson_name))
    
    if not other_lessons:
        content_rows = frappe.db.sql("""
            SELECT content_type, content_reference 
            FROM `tabLMS Chapter Content` 
            WHERE `parent` = %s
        """, (chapter_name,), as_dict=True)
        
        for crow in content_rows:
            ctype = crow.get("content_type")
            cref = crow.get("content_reference")
            _delete_content_record_sql(ctype, cref)
                
        frappe.db.sql("DELETE FROM `tabLMS Chapter Content` WHERE `parent` = %s", (chapter_name,))
        frappe.db.sql("DELETE FROM `tabLMS Chapter Progress` WHERE `chapter` = %s", (chapter_name,))
        frappe.db.sql("DELETE FROM `tabLMS Chapter` WHERE `name` = %s", (chapter_name,))
        
    frappe.db.commit()
    return {"status": "success"}

@frappe.whitelist(allow_guest=False)
def get_admin_dashboard_modules():
    modules = frappe.get_all("LMS Module", 
        fields=["name", "module_name", "status", "creation", "modified", "image", "is_mandatory", "duration"],
        order_by="creation desc"
    )
    
    module_names = [m.name for m in modules]
    categories = []
    if module_names:
        categories = frappe.get_all("LMS Module Category", 
            filters={"parent": ["in", module_names]}, 
            fields=["parent", "category"]
        )
        
    cat_map = {}
    for cat in categories:
        if cat.parent not in cat_map:
            cat_map[cat.parent] = []
        cat_map[cat.parent].append({"category": cat.category})
    
    for mod in modules:
        mod.category = cat_map.get(mod.name, [])
        # Get total assigned learners who started
        total = frappe.db.count("LMS Module Tracker", {"module": mod.name, "status": ["!=", "Unassigned"]})
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
        
        from lms.backend.api.common.module_detail import get_module_duration_mins, format_duration_str
        curriculum_mins = get_module_duration_mins(mod.name)
        if curriculum_mins > 0:
            mod.duration = curriculum_mins
        mod.duration_str = format_duration_str(mod.duration or 0)
        
    return modules

@frappe.whitelist(allow_guest=False)
def delete_module(module_name):
    if not module_name:
        frappe.throw("Module Name is required")
        
    module_exists = frappe.db.sql("SELECT name FROM `tabLMS Module` WHERE `name` = %s", (module_name,), pluck="name")
    if not module_exists:
        return {"status": "not_found"}

    # 1. Check if it's part of a learning path
    paths = frappe.db.sql("""
        SELECT DISTINCT parent FROM `tabLMS Learning Path Course`
        WHERE `module` = %s
    """, (module_name,), pluck="parent")
    if paths:
        frappe.throw(f"Cannot delete module because it is used in Learning Path(s): {', '.join(paths)}. Please remove it from the path(s) first.")

    # 2. Delete Trackers and associated Quiz Submissions + Progress child tables
    tracker_names = frappe.db.sql("""
        SELECT name FROM `tabLMS Module Tracker` WHERE `module` = %s
    """, (module_name,), pluck="name")
    if tracker_names:
        sub_names = frappe.db.sql("""
            SELECT name FROM `tabLMS Quiz Submission` WHERE `enrollment` IN %s
        """, (tuple(tracker_names),), pluck="name")
        if sub_names:
            frappe.db.sql("DELETE FROM `tabLMS Quiz Submission Detail` WHERE `parent` IN %s", (tuple(sub_names),))
            frappe.db.sql("DELETE FROM `tabLMS Quiz Submission` WHERE `name` IN %s", (tuple(sub_names),))

        frappe.db.sql("DELETE FROM `tabLMS Lesson Progress` WHERE `parent` IN %s", (tuple(tracker_names),))
        frappe.db.sql("DELETE FROM `tabLMS Chapter Progress` WHERE `parent` IN %s", (tuple(tracker_names),))
        frappe.db.sql("DELETE FROM `tabLMS Content Progress` WHERE `parent` IN %s", (tuple(tracker_names),))
        frappe.db.sql("DELETE FROM `tabLMS Interaction Response` WHERE `parent` IN %s", (tuple(tracker_names),))
        frappe.db.sql("DELETE FROM `tabLMS Module Tracker` WHERE `name` IN %s", (tuple(tracker_names),))

    # 3. Delete Module Assignments and child tables
    assignment_names = frappe.db.sql("""
        SELECT name FROM `tabLMS Module Assignment` WHERE `module` = %s
    """, (module_name,), pluck="name")
    if assignment_names:
        frappe.db.sql("DELETE FROM `tabLMS Assignment Team` WHERE `parent` IN %s", (tuple(assignment_names),))
        frappe.db.sql("DELETE FROM `tabLMS Assignment User` WHERE `parent` IN %s", (tuple(assignment_names),))
        frappe.db.sql("DELETE FROM `tabLMS Module Assignment` WHERE `name` IN %s", (tuple(assignment_names),))

    # 4. Delete Certificates, Path Module Progress, Badges
    frappe.db.sql("DELETE FROM `tabLMS Certificate` WHERE `module` = %s", (module_name,))
    frappe.db.sql("DELETE FROM `tabLMS Path Module Progress` WHERE `module` = %s", (module_name,))
    frappe.db.sql("DELETE FROM `tabLMS Learner Badge` WHERE `module` = %s", (module_name,))

    # 5. Delete Learner Notes
    frappe.db.sql("DELETE FROM `tabLMS Learner Note` WHERE `reference_module` = %s", (module_name,))

    # 6. Delete Discussions and messages
    discussion_names = frappe.db.sql("""
        SELECT name FROM `tabLMS Discussion` WHERE `reference_module` = %s
    """, (module_name,), pluck="name")
    if discussion_names:
        frappe.db.sql("DELETE FROM `tabLMS Discussion Message` WHERE `parent` IN %s", (tuple(discussion_names),))
        frappe.db.sql("DELETE FROM `tabLMS Discussion` WHERE `name` IN %s", (tuple(discussion_names),))

    # 7. Delete Lessons, Chapters, and Content blocks attached to this module if not used elsewhere
    lesson_names = frappe.db.sql("""
        SELECT lesson FROM `tabLMS Module Lesson Child` WHERE `parent` = %s
    """, (module_name,), pluck="lesson")
    for l_name in lesson_names:
        other_modules = frappe.db.sql("""
            SELECT parent FROM `tabLMS Module Lesson Child`
            WHERE `lesson` = %s AND `parent` != %s
        """, (l_name, module_name))
        if not other_modules:
            chapter_names = frappe.db.sql("""
                SELECT chapter FROM `tabLMS Lesson Chapter` WHERE `parent` = %s
            """, (l_name,), pluck="chapter")
            for ch_name in chapter_names:
                other_lessons = frappe.db.sql("""
                    SELECT parent FROM `tabLMS Lesson Chapter`
                    WHERE `chapter` = %s AND `parent` != %s
                """, (ch_name, l_name))
                if not other_lessons:
                    content_rows = frappe.db.sql("""
                        SELECT content_type, content_reference 
                        FROM `tabLMS Chapter Content` 
                        WHERE `parent` = %s
                    """, (ch_name,), as_dict=True)
                    for crow in content_rows:
                        ctype = crow.get("content_type")
                        cref = crow.get("content_reference")
                        _delete_content_record_sql(ctype, cref)

                    frappe.db.sql("DELETE FROM `tabLMS Chapter Content` WHERE `parent` = %s", (ch_name,))
                    frappe.db.sql("DELETE FROM `tabLMS Chapter Progress` WHERE `chapter` = %s", (ch_name,))
                    frappe.db.sql("DELETE FROM `tabLMS Chapter` WHERE `name` = %s", (ch_name,))

            frappe.db.sql("DELETE FROM `tabLMS Lesson Chapter` WHERE `parent` = %s", (l_name,))
            frappe.db.sql("DELETE FROM `tabLMS Lesson Progress` WHERE `lesson` = %s", (l_name,))
            frappe.db.sql("DELETE FROM `tabLMS Lesson` WHERE `name` = %s", (l_name,))

    # 8. Delete Module child tables
    frappe.db.sql("DELETE FROM `tabLMS Module Category` WHERE `parent` = %s", (module_name,))
    frappe.db.sql("DELETE FROM `tabLMS Module Lesson Child` WHERE `parent` = %s", (module_name,))
    frappe.db.sql("DELETE FROM `tabLMS Module Version` WHERE `parent` = %s", (module_name,))

    # 9. Delete the module itself
    frappe.db.sql("DELETE FROM `tabLMS Module` WHERE `name` = %s", (module_name,))
    frappe.db.commit()

    return {"status": "success"}

@frappe.whitelist(allow_guest=False)
def duplicate_module(module_name):
    if not module_name:
        frappe.throw("Module Name is required")
        
    original = frappe.get_doc("LMS Module", module_name)
    
    import re
    # Extract base name by removing any trailing " (Copy)" or " (Copy X)"
    match = re.match(r'^(.*?)(?:\s*\(Copy(?:\s+\d+)?\))?$', original.module_name)
    base_name = match.group(1).strip() if match else original.module_name.strip()
    
    new_name = f"{base_name} (Copy)"
    counter = 1
    
    while frappe.db.exists("LMS Module", {"module_name": new_name}):
        new_name = f"{base_name} (Copy {counter})"
        counter += 1
        
    # Create copy of module shell
    new_module = frappe.copy_doc(original)
    new_module.module_name = new_name
    new_module.status = "Draft"
    new_module.set("lessons", [])
    new_module.insert(ignore_permissions=True)
    
    # Deep copy lessons
    for old_lesson_row in original.lessons:
        old_lesson = frappe.get_doc("LMS Lesson", old_lesson_row.lesson)
        new_lesson = frappe.copy_doc(old_lesson)
        new_lesson.set("chapters", [])
        
        # Deep copy chapters
        for old_chapter_row in old_lesson.chapters:
            old_chapter = frappe.get_doc("LMS Chapter", old_chapter_row.chapter)
            new_chapter = frappe.copy_doc(old_chapter)
            new_chapter.set("contents", [])
            
            # Deep copy contents
            for old_content_row in old_chapter.contents:
                old_content = frappe.get_doc(old_content_row.content_type, old_content_row.content_reference)
                new_content = frappe.copy_doc(old_content)
                
                if old_content_row.content_type == "LMS Quiz Content" and getattr(new_content, "quiz", None):
                    old_quiz = frappe.get_doc("LMS Quiz", new_content.quiz)
                    new_quiz = frappe.copy_doc(old_quiz)
                    new_quiz.insert(ignore_permissions=True)
                    new_content.quiz = new_quiz.name
                    
                elif old_content_row.content_type == "LMS Assessment Content" and getattr(new_content, "assessment", None):
                    old_quiz = frappe.get_doc("LMS Quiz", new_content.assessment)
                    new_quiz = frappe.copy_doc(old_quiz)
                    new_quiz.insert(ignore_permissions=True)
                    new_content.assessment = new_quiz.name
                    
                new_content.insert(ignore_permissions=True)
                new_chapter.append("contents", {
                    "content_type": old_content_row.content_type,
                    "content_reference": new_content.name,
                    "order": old_content_row.order
                })
                
            new_chapter.insert(ignore_permissions=True)
            new_lesson.append("chapters", {
                "chapter": new_chapter.name,
                "order": old_chapter_row.order or old_chapter_row.idx
            })
            
        new_lesson.insert(ignore_permissions=True)
        new_module.append("lessons", {
            "lesson": new_lesson.name,
            "order": old_lesson_row.order or old_lesson_row.idx
        })
        
    new_module.save(ignore_permissions=True)
    
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
    
    # New dynamic fields
    quiz.points_per_question = quiz_data.get("points_per_question", 0)
    quiz.allow_retakes = quiz_data.get("allow_retakes", 0)
    quiz.randomize_options = quiz_data.get("randomize_options", 0)
    quiz.show_results = quiz_data.get("show_results", 0)
    quiz.show_pass_fail = quiz_data.get("show_pass_fail", 0)
    quiz.show_final_score = quiz_data.get("show_final_score", 0)
    quiz.show_correct_answers = quiz_data.get("show_correct_answers", 0)
    quiz.show_explanations = quiz_data.get("show_explanations", 0)
    quiz.allow_unanswered = quiz_data.get("allow_unanswered", 0)
    quiz.evaluation_method = quiz_data.get("evaluation_method", "AI-assisted evaluation")
    
    # Auto-set quiz_type based on the content type that contains this quiz
    quiz.quiz_type = "QA Assessment" if content_link.content_type == "LMS Assessment Content" else "Quiz"
    
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
        
        # Handle Scenario Based criteria mapped to options
        if q_doc.question_type == "Scenario Based" and q_data.get("criteria"):
            for crit in q_data.get("criteria", []):
                crit_name = (crit.get("name") or "").strip()
                if not crit_name:
                    continue
                q_doc.append("options", {
                    "option_text": crit_name,
                    "score": crit.get("score", 0),
                    "is_correct": 0
                })
        else:
            for opt in q_data.get("options", []):
                opt_text = (opt.get("option_text") or "").strip()
                if not opt_text:
                    continue
                q_doc.append("options", {
                    "option_text": opt_text,
                    "is_correct": opt.get("is_correct", 0),
                    "score": 0
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
def update_chapter_media(chapter_name, base_media=None, video_url=None, iframe_url=None, slides_json=None, duration=None, allow_skipping=None, track_interaction=None, content_idx=0):
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
    if duration is not None and hasattr(content_doc, "duration"):
        try:
            content_doc.duration = float(duration)
        except (ValueError, TypeError):
            pass
            
    if allow_skipping is not None and content_doc.meta.has_field("allow_skipping"):
        content_doc.allow_skipping = int(allow_skipping)


    if track_interaction is not None and content_doc.meta.has_field("track_interaction"):
        content_doc.track_interaction = int(track_interaction)
            
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
        if order:
            frappe.db.sql("""
                DELETE FROM `tabLMS Module Lesson Child`
                WHERE `parent` = %s AND `lesson` NOT IN %s
            """, (module_name, tuple(order)))
        else:
            frappe.db.sql("DELETE FROM `tabLMS Module Lesson Child` WHERE `parent` = %s", module_name)
            
        for idx, lesson_name in enumerate(order):
            frappe.db.sql("""
                UPDATE `tabLMS Module Lesson Child`
                SET `order` = %s, `idx` = %s
                WHERE `parent` = %s AND `lesson` = %s
            """, (idx + 1, idx + 1, module_name, lesson_name))
            
        frappe.db.commit()
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
        if order:
            frappe.db.sql("""
                DELETE FROM `tabLMS Lesson Chapter`
                WHERE `parent` = %s AND `chapter` NOT IN %s
            """, (lesson_name, tuple(order)))
        else:
            frappe.db.sql("DELETE FROM `tabLMS Lesson Chapter` WHERE `parent` = %s", lesson_name)
            
        for idx, chapter_name in enumerate(order):
            exists = frappe.db.exists("LMS Lesson Chapter", {"parent": lesson_name, "chapter": chapter_name})
            if exists:
                frappe.db.sql("""
                    UPDATE `tabLMS Lesson Chapter`
                    SET `order` = %s, `idx` = %s
                    WHERE `parent` = %s AND `chapter` = %s
                """, (idx + 1, idx + 1, lesson_name, chapter_name))
            else:
                frappe.db.sql("""
                    UPDATE `tabLMS Lesson Chapter`
                    SET `order` = %s, `idx` = %s, `parent` = %s
                    WHERE `chapter` = %s
                """, (idx + 1, idx + 1, lesson_name, chapter_name))
                
        frappe.db.commit()
        return {"status": "success"}
    except Exception as e:
        frappe.log_error("reorder_chapters failed", str(e))
        frappe.throw(str(e))


@frappe.whitelist()
def toggle_module_archive(module_name):
    doc = frappe.db.get_value("LMS Module", module_name, ["status", "previous_status"], as_dict=True)
    status = doc.status

    if status == "Archived":
        # Restore to previous state (Published or Draft), default to Draft if missing
        restore_status = doc.previous_status or "Draft"
        frappe.db.set_value("LMS Module", module_name, {
            "status": restore_status,
            "previous_status": None
        })
        return restore_status
    else:
        # Archive: save current status so we can restore later
        frappe.db.set_value("LMS Module", module_name, {
            "previous_status": status,
            "status": "Archived"
        })
        return "Archived"

@frappe.whitelist(allow_guest=False)
def get_teams():
    teams = frappe.get_all("LMS Team", fields=["name", "team_name"])
    for team in teams:
        learner_count = frappe.db.count("LMS Team Member", {"parent": team.name, "parenttype": "LMS Team"})
        team.learner_count = learner_count
    return teams

@frappe.whitelist()
def reissue_certificates(certificate_ids):
    import json
    if isinstance(certificate_ids, str):
        certificate_ids = json.loads(certificate_ids)
        
    for cert_id in certificate_ids:
        # Update the issue date to today and ensure the certificate is valid again
        frappe.db.set_value("LMS Certificate", cert_id, {
            "issued_on": frappe.utils.nowdate(),
            "status": "Reissued",
            "revocation_reason": None,
            "custom_revocation_reason": None,
            "revoked_by": None,
            "revoked_on": None,
            "certificate_pdf": None,
            "pdf_status": "Pending",
            "pdf_file_url": None
        })
        
        # Delete old generated PDF files from Frappe to save disk space
        old_files = frappe.get_all("File", filters={
            "attached_to_doctype": "LMS Certificate",
            "attached_to_name": cert_id
        })
        for f in old_files:
            frappe.delete_doc("File", f.name, ignore_permissions=True)
        
    frappe.db.commit()
    return True

@frappe.whitelist(allow_guest=False)
def get_module_learners(module_name):
    from frappe.utils import add_days, getdate, today
    
    # Fetch assignments
    assignments = frappe.get_all("LMS Module Assignment", filters={"module": module_name}, fields=["name", "assignment_type", "duration"])
    
    # Build set of admin users to exclude (LMS-Admin or System Manager)
    admin_role_entries = frappe.get_all("Has Role", filters={"role": "LMS-Admin"}, pluck="parent", ignore_permissions=True)
    admin_users_set = set(admin_role_entries)

    users = {}

    for a in assignments:
        duration = a.duration or 0
        creation_date = a.creation
        if a.assignment_type == "Everyone":
            # Dynamically resolve to all active learners (has LMS-Learner or LMS-TL role)
            lms_roles = frappe.get_all("Has Role", filters={"role": ["in", ["LMS-Learner", "LMS-TL"]]}, fields=["parent"])
            valid_users = [r.parent for r in lms_roles if r.parent not in ["Administrator", "Guest"] and r.parent not in admin_users_set]
            
            all_users = frappe.get_all(
                "User",
                filters={
                    "enabled": 1,
                    "name": ["in", valid_users] if valid_users else ["in", ["__nobody__"]]
                },
                fields=["name"]
            )
            for u in all_users:
                if u.name not in users:
                    users[u.name] = {"duration": duration, "assigned_via": "Everyone", "creation": creation_date}
        elif a.assignment_type == "Manual":
            learners = frappe.get_all("LMS Assignment User", filters={"parent": a.name}, fields=["user"])
            for l in learners:
                if l.user not in users and l.user not in admin_users_set:
                    users[l.user] = {"duration": duration, "assigned_via": "Manual", "creation": creation_date}
        else:
            teams = frappe.get_all("LMS Assignment Team", filters={"parent": a.name}, fields=["team"])
            for t in teams:
                members = frappe.get_all("LMS Team Member", filters={"parent": t.team, "parentfield": "learners"}, fields=["user"])
                for m in members:
                    if m.user not in users and m.user not in admin_users_set:
                        users[m.user] = {"duration": duration, "assigned_via": "Team", "team": t.team, "creation": creation_date}


    if not users:
        return {
            "learners": []
        }
        
    enabled_users_set = set(frappe.get_all("User", filters={"enabled": 1, "name": ["in", list(users.keys())]}, pluck="name"))
    users = {k: v for k, v in users.items() if k in enabled_users_set}
    
    if not users:
        return {
            "learners": []
        }
        
    user_docs = frappe.get_all("User", filters={"name": ["in", list(users.keys())]}, fields=["name", "full_name", "user_image"])
    user_map = {u.name: u for u in user_docs}
    
    team_members = frappe.get_all("LMS Team Member", filters={"user": ["in", list(users.keys())]}, fields=["user", "parent"])
    user_team_map = {u: [] for u in users.keys()}
    if team_members:
        team_names = frappe.get_all("LMS Team", filters={"name": ["in", [m.parent for m in team_members]]}, fields=["name", "team_name"])
        team_name_map = {t.name: t.team_name for t in team_names}
        for m in team_members:
            team_name = team_name_map.get(m.parent, m.parent)
            if team_name not in user_team_map[m.user]:
                user_team_map[m.user].append(team_name)
    
    # Create final map joining with commas
    user_team_map = {u: ", ".join(teams) for u, teams in user_team_map.items()}
    
    trackers = frappe.get_all("LMS Module Tracker", filters={"module": module_name, "user": ["in", list(users.keys())]}, fields=["name", "user", "status", "progress_percentage", "total_score", "started_on", "modified", "completed_on"])
    tracker_map = {t.user: t for t in trackers}

    # ── Resolve passing percentage and quiz submissions ───────────────────
    PASSING_PERCENTAGE = 60  # default fallback
    quiz_name = None
    try:
        # Assessments are stored in the LMS Module Assessment child table
        assessments = frappe.get_all(
            "LMS Module Assessment",
            filters={"parent": module_name, "parenttype": "LMS Module"},
            fields=["assessment"],
            limit=1
        )
        if assessments:
            quiz_name = assessments[0].assessment
            quiz_doc = frappe.get_doc("LMS Quiz", quiz_name)
            if quiz_doc.passing_percentage and quiz_doc.passing_percentage > 0:
                PASSING_PERCENTAGE = float(quiz_doc.passing_percentage)
    except Exception:
        pass

    # Map user -> best quiz submission score (None if no submission)
    submission_score_map = {}  # user -> score (0-100) or None
    tracker_name_list = [t.name for t in trackers] if trackers else []
    tracker_name_to_user = {t.name: t.user for t in trackers} if trackers else {}

    if tracker_name_list:
        # Fetch submissions for any quiz tied to this module's trackers
        filters_dict = {"enrollment": ["in", tracker_name_list]}
        if quiz_name:
            filters_dict["quiz"] = quiz_name
            
        submissions = frappe.get_all(
            "LMS Quiz Submission",
            filters=filters_dict,
            fields=["enrollment", "score"]
        )
        # Keep the best (highest) score per tracker/enrollment
        for sub in submissions:
            user_key = tracker_name_to_user.get(sub.enrollment)
            if user_key:
                current_best = submission_score_map.get(user_key)
                sub_score = float(sub.score) if sub.score is not None else 0.0
                if current_best is None or sub_score > current_best:
                    submission_score_map[user_key] = sub_score

    stats = {"totalAssigned": len(users), "notStarted": 0, "inProgress": 0, "completed": 0, "overdue": 0}
    needs_attention = {"overdueLearning": 0, "inactiveLearners": 0, "lowAssessmentScores": 0}
    
    results = []
    seven_days_ago = add_days(today(), -7)
    
    for user, data in users.items():
        tracker = tracker_map.get(user)
        
        # Skip learners who have been explicitly unassigned — their data is preserved
        # but they should not appear in the active learners list
        if tracker and tracker.status == "Unassigned":
            continue
        
        u_info = user_map.get(user)
        department = user_team_map.get(user, "Unknown")
        
        learner_info = {
            "name": user,
            "fullName": u_info.full_name if u_info else user,
            "avatar": u_info.user_image if u_info else None,
            "department": department,
            "progress": 0,
            "status": "Not Started",
            "score": None,
            "dueDate": None,
            "lastActivity": None,
            "isOverdue": False,
            "needsAttention": False,
            "hasAssessment": bool(quiz_name) or (user in submission_score_map),
            "assignedDate": data.get("creation"),
            "trackerName": tracker.name if tracker else None
        }
        
        start_dt = getdate(tracker.started_on) if tracker and tracker.started_on else None
        if data.get("duration") and start_dt:
            due = add_days(start_dt, data["duration"])
            learner_info["dueDate"] = str(due)
            if getdate(due) < getdate(today()) and (not tracker or tracker.status != "Completed"):
                learner_info["isOverdue"] = True
                stats["overdue"] += 1
                needs_attention["overdueLearning"] += 1
                learner_info["needsAttention"] = True
        else:
            learner_info["dueDate"] = None

        if tracker:
            learner_info["status"] = tracker.status
            learner_info["progress"] = tracker.progress_percentage or 0
            learner_info["lastActivity"] = tracker.modified

            # Score resolution — two-tier:
            #   1. LMS Quiz Submission (accurate per-attempt record)
            #   2. tracker.total_score fallback when status is Completed/Failed
            #      (legacy path: score was written directly to the tracker)
            submitted_score = submission_score_map.get(user)  # None if no submission record
            if submitted_score is not None:
                learner_info["score"] = float(submitted_score)
                if learner_info["score"] < PASSING_PERCENTAGE:
                    needs_attention["lowAssessmentScores"] += 1
                    learner_info["needsAttention"] = True
            elif tracker.status in ("Completed", "Failed") and tracker.total_score is not None and float(tracker.total_score) >= 0:
                # Legacy: score stored only in tracker, not in a submission record
                learner_info["score"] = float(tracker.total_score)
                if learner_info["score"] < PASSING_PERCENTAGE:
                    needs_attention["lowAssessmentScores"] += 1
                    learner_info["needsAttention"] = True
            else:
                # If they completed the module but have absolutely no score,
                # we don't treat it as "Failed: 0%", we just keep it as None (--)
                learner_info["score"] = None  # Not attempted

            learner_info["passingPercentage"] = PASSING_PERCENTAGE

            if tracker.status == "Completed":
                stats["completed"] += 1
            elif tracker.status in ["In Progress", "Failed"]:
                stats["inProgress"] += 1
            else:
                stats["notStarted"] += 1
                
            if getdate(tracker.modified) < getdate(seven_days_ago) and tracker.status != "Completed":
                learner_info["isInactive"] = True
                needs_attention["inactiveLearners"] += 1
                learner_info["needsAttention"] = True
        else:
            stats["notStarted"] += 1
            # If no tracker, check if they were assigned more than 7 days ago
            if data.get("creation") and getdate(data.get("creation")) < getdate(seven_days_ago):
                learner_info["isInactive"] = True
                needs_attention["inactiveLearners"] += 1
                learner_info["needsAttention"] = True
            
        results.append(learner_info)
        
    # Sort results by recent activity (lastActivity or assignedDate)
    results.sort(
        key=lambda x: str(x.get("lastActivity") or x.get("assignedDate") or ""), 
        reverse=True
    )
        
    return {
        "stats": stats,
        "needsAttention": needs_attention,
        "learners": results
    }
