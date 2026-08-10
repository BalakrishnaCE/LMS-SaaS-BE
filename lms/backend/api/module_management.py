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
            chapters.append({
                "name": chapter.name,
                "title": chapter.title,
                "scoring": chapter.scoring,
                "order": ch.order
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

@frappe.whitelist(allow_guest=False)
def add_chapter(lesson_name, chapter_title):
    if not lesson_name or not chapter_title:
        frappe.throw("Lesson Name and Chapter Title are required")
        
    # Check if chapter exists, else create
    if not frappe.db.exists("LMS Chapter", {"title": chapter_title}):
        chapter = frappe.get_doc({
            "doctype": "LMS Chapter",
            "title": chapter_title,
            "scoring": 0
        })
        chapter.insert(ignore_permissions=True)
    else:
        chapter = frappe.get_doc("LMS Chapter", {"title": chapter_title})
        
    lesson = frappe.get_doc("LMS Lesson", lesson_name)
    
    # Check if attached
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
    return {"status": "success"}

@frappe.whitelist(allow_guest=False)
def remove_chapter(lesson_name, chapter_name):
    lesson = frappe.get_doc("LMS Lesson", lesson_name)
    lesson.chapters = [ch for ch in lesson.chapters if ch.chapter != chapter_name]
    lesson.save(ignore_permissions=True)
    return {"status": "success"}
