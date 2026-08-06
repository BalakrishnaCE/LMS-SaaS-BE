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
