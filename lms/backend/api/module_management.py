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
            
            content_type = "document"
            content_data = None
            if hasattr(chapter, "contents") and chapter.contents:
                content_link = chapter.contents[0]
                raw_type = content_link.content_type
                reverse_map = {
                    'LMS Text Content': 'document',
                    'LMS Video Content': 'video',
                    'LMS Audio Content': 'audio',
                    'LMS Document Content': 'presentation'
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
                except Exception:
                    content_data = None

            chapters.append({
                "name": chapter.name,
                "title": chapter.title,
                "scoring": chapter.scoring,
                "order": ch.order,
                "contentType": content_type,
                "contentData": content_data
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
    if not lesson_name or not chapter_title:
        frappe.throw("Lesson Name and Chapter Title are required")
        
    type_map = {
        'document': 'LMS Text Content', # Maps to text_block (Rich Text)
        'video': 'LMS Video Content',
        'audio': 'LMS Audio Content',
        'presentation': 'LMS Document Content', # Maps to base_media (File upload)
        'quiz': 'LMS Text Content', 
        'iframe': 'LMS Text Content',
        'assessment': 'LMS Text Content',
        'ai': 'LMS Text Content'
    }
    doctype_name = type_map.get(content_type, 'LMS Text Content')
        
    # Always create a new chapter
    chapter = frappe.get_doc({
        "doctype": "LMS Chapter",
        "title": chapter_title,
        "scoring": 0
    })
    chapter.insert(ignore_permissions=True)
    
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
    except Exception as e:
        frappe.log_error("Failed to create content doc", str(e))
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
        fields=["name", "module_name", "category", "status", "creation", "modified", "image", "is_mandatory"],
        order_by="creation desc"
    )
    
    for mod in modules:
        # Get total assigned learners who started
        total = frappe.db.count("LMS Module Tracker", {"module": mod.name})
        completed = frappe.db.count("LMS Module Tracker", {"module": mod.name, "status": "Completed"})
        
        mod.totalLearners = total
        mod.completedLearners = completed
        mod.completionRate = (completed / total * 100) if total > 0 else 0
        
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
    
    # Create copy
    new_module = frappe.copy_doc(original)
    new_module.module_name = f"{original.module_name} (Copy)"
    new_module.status = "Draft"
    new_module.insert(ignore_permissions=True)
    
    return {"status": "success", "new_module_id": new_module.name}
