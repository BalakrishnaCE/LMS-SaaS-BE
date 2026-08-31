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

from lms.backend.api.admin import module_management

@frappe.whitelist()
def get_curriculum(module_name):
    return module_management.get_curriculum(module_name)

@frappe.whitelist()
def add_lesson(module_name, lesson_name, description=""):
    return module_management.add_lesson(module_name, lesson_name, description)

@frappe.whitelist()
def add_chapter(lesson_name, chapter_title, content_type="document", content_data=None):
    return module_management.add_chapter(lesson_name, chapter_title, content_type, content_data)

@frappe.whitelist()
def add_content_block(chapter_name, content_type, title=None, content_data=None):
    return module_management.add_content_block(chapter_name, content_type, title, content_data)

@frappe.whitelist()
def remove_content_block(chapter_name, content_reference):
    return module_management.remove_content_block(chapter_name, content_reference)

@frappe.whitelist()
def reorder_content_blocks(chapter_name, ordered_references):
    return module_management.reorder_content_blocks(chapter_name, ordered_references)

@frappe.whitelist()
def remove_lesson(module_name, lesson_name):
    return module_management.remove_lesson(module_name, lesson_name)

@frappe.whitelist()
def remove_chapter(lesson_name, chapter_name):
    return module_management.remove_chapter(lesson_name, chapter_name)

@frappe.whitelist()
def validate_iframe_url(url):
    import requests
    
    if not url:
        return {"state": "invalidUrl"}
        
    try:
        # Ping the URL with a short timeout to prevent hanging the server
        response = requests.head(url, timeout=3, allow_redirects=True)
        if response.status_code == 405:
            # Fallback to GET if HEAD is not allowed
            response = requests.get(url, timeout=3, stream=True, allow_redirects=True)
            response.close()
            
        # If we got a 401 or 403, we can assume it requires authentication
        if response.status_code in [401, 403]:
            return {"state": "authRequired"}
            
        # Check security headers
        x_frame_options = response.headers.get('X-Frame-Options', '').upper()
        csp = response.headers.get('Content-Security-Policy', '').lower()
        
        # DENY or SAMEORIGIN means we cannot frame it (since this is a SaaS platform)
        if 'DENY' in x_frame_options or 'SAMEORIGIN' in x_frame_options:
            return {"state": "embeddingRestricted"}
            
        # frame-ancestors restricts who can frame this site.
        # If present, it often restricts to self or specific origins, so we flag it.
        if 'frame-ancestors' in csp and ('self' in csp or 'none' in csp):
            return {"state": "embeddingRestricted"}
            
        return {"state": "live"}
        
    except requests.exceptions.RequestException:
        # If DNS fails, connection times out, etc.
        return {"state": "unavailable"}
