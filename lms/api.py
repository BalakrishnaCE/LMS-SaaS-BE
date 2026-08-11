import frappe

@frappe.whitelist(allow_guest=True)
def get_tenant_theme():
    # Gets the saved color directly from Redis High-Speed RAM
    color = frappe.cache().get_value("theme_color")
    
    # Redis sometimes returns binary strings, so we decode it safely
    if color and isinstance(color, bytes):
        color = color.decode('utf-8')
        
    return {"color": color or "#2563eb"}

@frappe.whitelist(allow_guest=True)
def save_tenant_theme(color):
    # Saves the color instantly to Redis (Bypassing Guest DB restrictions!)
    frappe.cache().set_value("theme_color", color)
    return {"status": "success"}

@frappe.whitelist(allow_guest=True)
def get_csrf_token():
    return frappe.sessions.get_csrf_token()

@frappe.whitelist()
def delete_file(file_url):
    if not file_url:
        return {"status": "failed", "message": "No file_url provided"}
    
    file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
    if file_name:
        frappe.delete_doc("File", file_name, ignore_permissions=True)
        return {"status": "success"}
    return {"status": "not_found"}

# --- Curriculum Builder Endpoints ---

from lms.backend.api import module_management

@frappe.whitelist()
def get_curriculum(module_name):
    return module_management.get_curriculum(module_name)

@frappe.whitelist()
def add_lesson(module_name, lesson_name, description=""):
    return module_management.add_lesson(module_name, lesson_name, description)

@frappe.whitelist()
def add_chapter(lesson_name, chapter_title):
    return module_management.add_chapter(lesson_name, chapter_title)

@frappe.whitelist()
def remove_lesson(module_name, lesson_name):
    return module_management.remove_lesson(module_name, lesson_name)

@frappe.whitelist()
def remove_chapter(lesson_name, chapter_name):
    return module_management.remove_chapter(lesson_name, chapter_name)
