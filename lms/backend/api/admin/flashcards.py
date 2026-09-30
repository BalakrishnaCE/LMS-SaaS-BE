import frappe
import json

@frappe.whitelist()
def update_chapter_flashcards(chapter_name, flashcards_enabled, flashcards):
    if not chapter_name:
        frappe.throw("Chapter Name is required")
        
    if isinstance(flashcards_enabled, str):
        flashcards_enabled = json.loads(flashcards_enabled)
        
    if isinstance(flashcards, str):
        flashcards = json.loads(flashcards)
        
    chapter = frappe.get_doc("LMS Chapter", chapter_name)
    
    # Find existing flashcard content
    flashcard_content_link = None
    for content in chapter.contents:
        if content.content_type == "LMS Flashcard Content":
            flashcard_content_link = content
            break
            
    if not flashcards_enabled:
        if flashcard_content_link:
            frappe.db.sql("""
                DELETE FROM `tabLMS Chapter Content`
                WHERE `parent` = %s AND `name` = %s
            """, (chapter_name, flashcard_content_link.name))
            frappe.db.commit()
        return {"status": "success"}
        
    # If enabled, update or create
    is_new = False
    if flashcard_content_link:
        flashcard_doc = frappe.get_doc("LMS Flashcard Content", flashcard_content_link.content_reference)
    else:
        flashcard_doc = frappe.new_doc("LMS Flashcard Content")
        flashcard_doc.title = f"Flashcards for {chapter.title}"
        is_new = True
        
    # Clear and rebuild interactive_elements
    flashcard_doc.set("interactive_elements", [])
    
    # We need to know the 'Interaction Type' for Flashcard. 
    # Usually it's "Flashcard" or similar. If we must provide it, let's look up or hardcode.
    # The doc says "Link to the corresponding LMS Interactive Type."
    # Let's try to get or create it.
    if not frappe.db.exists("LMS Interactive Type", "Flashcard"):
        frappe.get_doc({
            "doctype": "LMS Interactive Type",
            "name": "Flashcard",
            "type_name": "Flashcard"
        }).insert(ignore_permissions=True)
        
    for card in flashcards:
        flashcard_doc.append("interactive_elements", {
            "interaction_type": "Flashcard",
            "element_text": card.get("front", ""),
            "secondary_text": card.get("back", "")
        })
        
    if is_new:
        flashcard_doc.insert(ignore_permissions=True)
    else:
        flashcard_doc.flags.ignore_version = True
        flashcard_doc.save(ignore_permissions=True)
    
    if not flashcard_content_link:
        current_count = frappe.db.count("LMS Chapter Content", {"parent": chapter_name})
        frappe.get_doc({
            "doctype": "LMS Chapter Content",
            "parent": chapter_name,
            "parenttype": "LMS Chapter",
            "parentfield": "contents",
            "content_type": "LMS Flashcard Content",
            "content_reference": flashcard_doc.name,
            "order": current_count + 1,
            "idx": current_count + 1
        }).insert(ignore_permissions=True)
        
    return {"status": "success"}
