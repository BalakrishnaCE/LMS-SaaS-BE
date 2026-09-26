import frappe

@frappe.whitelist(allow_guest=True)
def get_tenant_settings():
    try:
        settings = frappe.get_single("LMS Settings")
        
        features = {}
        if hasattr(settings, "feature_toggles"):
            for toggle in settings.feature_toggles:
                features[toggle.feature_name] = bool(toggle.enabled)
                
        # Merge the distinct discussion toggle into features for unified frontend access
        features["Discussions"] = bool(settings.enable_discussions)
        return {
            # Brand Identity
            "color": settings.primary_color,
            "logo": settings.primary_logo,
            "light_logo": settings.light_logo,
            "app_icon": settings.app_icon,
            # Brand Color & Theme
            "default_theme": settings.default_theme or "Light",
            # General
            "brand_name": settings.brand_name,
            "organization_website": settings.organization_website,
            "industry": settings.industry,
            "company_size": settings.company_size,
            "learning_support_contact": settings.learning_support_contact,
            "support_link": settings.support_link,
            # Features
            "features": features
        }
    except Exception:
        return {
            "color": None,
            "logo": None,
            "light_logo": None,
            "app_icon": None,
            "default_theme": "Light",
            "brand_name": None,
            "organization_website": None,
            "industry": None,
            "company_size": None,
            "learning_support_contact": None,
            "support_link": None,
            "features": {}
        }

@frappe.whitelist()
def save_tenant_settings(**kwargs):
    # Security: Ensure only authorized users (System Managers) can modify tenant branding
    if not frappe.has_permission("LMS Settings", "write"):
        frappe.throw("Not permitted", frappe.PermissionError)
        
    settings = frappe.get_single("LMS Settings")
    
    # List of allowed fields that can be updated via this API
    allowed_fields = [
        # Brand Identity
        "primary_logo", "light_logo", "app_icon", "brand_name",
        # Brand Color & Theme
        "primary_color", "default_theme",
        # General
        "organization_website", "industry",
        "company_size", "learning_support_contact", "support_link"
    ]
    
    # Handle frontend aliases for backwards compatibility
    if "color" in kwargs:
        settings.primary_color = kwargs["color"]
        
    # 'logo' maps to the new 'primary_logo' field
    if "logo" in kwargs:
        settings.primary_logo = kwargs["logo"]
        
    for field in allowed_fields:
        if field in kwargs:
            setattr(settings, field, kwargs[field])
            
    settings.save(ignore_permissions=True)
    return {"status": "success"}

@frappe.whitelist(allow_guest=True)
def get_csrf_token():
    return frappe.sessions.get_csrf_token()

@frappe.whitelist(allow_guest=True)
def get_logged_user():
    return frappe.session.user

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


@frappe.whitelist()
def get_user_profile():
    user = frappe.session.user
    if user == "Guest":
        frappe.throw("Not logged in", frappe.PermissionError)
        
    doc = frappe.get_doc("User", user)
    roles = [r.role for r in doc.roles]
    
    return {
        "name": doc.name,
        "email": doc.email,
        "full_name": doc.full_name,
        "first_name": doc.first_name,
        "last_name": doc.last_name,
        "user_image": doc.user_image,
        "roles": roles
    }
