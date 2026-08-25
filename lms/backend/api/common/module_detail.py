import frappe
from frappe.utils import today, add_days, getdate, now
from frappe.utils.pdf import get_pdf

def get_estimated_hours_from_curriculum(module_name):
    from lms.backend.api.admin.module_management import get_curriculum
    try:
        curriculum = get_curriculum(module_name)
        total_mins = 0
        
        default_durations = {
            'text': 8,
            'file': 10,
            'video': 8,
            'audio': 10,
            'presentation': 15,
            'quiz': 8,
            'iframe': 5,
            'assessment': 30,
            'flashcard': 5,
            'document': 10
        }
        
        for lesson in curriculum:
            for chapter in lesson.get("chapters", []):
                primary_content = None
                if chapter.get("contents"):
                    primary_content = chapter["contents"][0]
                
                content_type = primary_content.get("contentType") if primary_content else chapter.get("contentType", "document")
                if content_type == 'document':
                    content_type = 'file'
                    
                true_duration = primary_content.get("contentData", {}).get("duration") if primary_content else None
                
                if content_type == 'interactive_video':
                    if true_duration:
                        total_mins += round(float(true_duration) * 1.5)
                    else:
                        total_mins += round(default_durations.get('video', 8) * 1.5)
                elif true_duration:
                    total_mins += round(float(true_duration))
                else:
                    total_mins += default_durations.get(content_type, 8)
                    
        return round(total_mins / 60, 1) if total_mins else 0
    except Exception:
        return 0

@frappe.whitelist(allow_guest=True)
def get_module_overview(module_id):
    module = frappe.get_doc("LMS Module", module_id)
    categories = [c.category for c in (module.category or [])]
    lesson_count = len(module.get("lessons", []))

    version_history = []
    current_version_val = "v1.0"
    for v in module.get("version_history", []):
        author_name = frappe.db.get_value("User", v.author, "full_name") or v.author
        ver_str = str(v.version) if v.version else "v1.0"
        if not ver_str.startswith("v") and not ver_str.startswith("V"):
            ver_str = f"v{ver_str}"
            
        if v.is_current:
            current_version_val = ver_str
            
        version_history.append({
            "version": ver_str,
            "is_current": bool(v.is_current),
            "description": v.description,
            "date": str(v.date)[:10] if v.date else "",
            "author": v.author,
            "author_name": author_name
        })
    version_history.reverse()
    
    if version_history and current_version_val == "v1.0" and not version_history[0].get("is_current"):
        current_version_val = version_history[0]["version"]

    assignment = frappe.get_all(
        "LMS Module Assignment",
        filters={"module": module_id},
        fields=["name", "duration", "creation"],
        limit=1,
        order_by="creation desc"
    )
    due_date = None
    days_remaining = None
    if assignment:
        a = assignment[0]
        if a.duration:
            due = add_days(getdate(a.creation), int(a.duration))
            due_date = str(due)
            delta = (getdate(due) - getdate(today())).days
            days_remaining = max(delta, 0)

    trackers = frappe.get_all(
        "LMS Module Tracker",
        filters={"module": module_id},
        fields=["status", "user", "total_score", "started_on", "creation"]
    )

    total_learners = len(trackers)
    passed  = sum(1 for t in trackers if t.status == "Completed")
    in_prog = sum(1 for t in trackers if t.status == "In Progress")
    failed  = sum(1 for t in trackers if t.status == "Failed")
    ns      = sum(1 for t in trackers if t.status == "Not started")
    pending = total_learners - passed

    passed_pct  = round((passed  / total_learners * 100) if total_learners else 0)
    inprog_pct  = round((in_prog / total_learners * 100) if total_learners else 0)
    failed_pct  = round((failed / total_learners * 100) if total_learners else 0)
    ns_pct      = max(0, 100 - passed_pct - inprog_pct - failed_pct) if total_learners else 0

    user_emails = list({t.user for t in trackers if t.user})
    dept_map = {}
    if user_emails:
        members = frappe.get_all(
            "LMS Team Member",
            filters={"user": ["in", user_emails]},
            fields=["parent", "user"]
        )
        teams = frappe.get_all("LMS Team", fields=["name", "team_name"])
        team_name_map = {t.name: t.team_name for t in teams}
        
        for m in members:
            dept_map[m.user] = team_name_map.get(m.parent, "Unknown")

    dept_stats = {}
    for t in trackers:
        dept = dept_map.get(t.user, "Unknown")
        if dept not in dept_stats:
            dept_stats[dept] = {"total": 0, "passed": 0, "pending": 0}
        dept_stats[dept]["total"] += 1
        if t.status == "Completed":
            dept_stats[dept]["passed"] += 1
        else:
            dept_stats[dept]["pending"] += 1

    departments = []
    for dept, s in dept_stats.items():
        progress = round((s["passed"] / s["total"] * 100) if s["total"] else 0)
        departments.append({
            "name": dept,
            "total": s["total"],
            "passed": s["passed"],
            "pending": s["pending"],
            "progress": progress,
        })
    departments.sort(key=lambda x: x["progress"], reverse=True)

    estimated_hours = getattr(module, "duration", None)
    if estimated_hours is None or estimated_hours == 0:
        estimated_hours = get_estimated_hours_from_curriculum(module_id)

    return {
        "module": {
            "id": module.name,
            "title": module.module_name,
            "description": module.description or "",
            "image": module.image or "",
            "status": module.status,
            "is_mandatory": bool(module.is_mandatory),
            "is_sequential": bool(getattr(module, "is_sequential", 0)),
            "allow_skip": bool(getattr(module, "allow_skip", 0)),
            "enable_discussion": bool(getattr(module, "enable_discussion", 0)),
            "enable_ai_flashcards": bool(getattr(module, "enable_ai_flashcards", 0)),
            "enable_certificate": bool(getattr(module, "enable_certificate", 0)),
            "version": current_version_val,
            "version_history": version_history,
            "categories": categories,
            "lesson_count": lesson_count,
            "estimated_hours": estimated_hours,
            "created_by": module.owner,
            "created_by_name": frappe.db.get_value("User", module.owner, "full_name") or module.owner,
            "creation": str(module.creation)[:10],
            "modified": str(module.modified)[:10],
            "visibility": getattr(module, "visibility", "All Departments"),
        },
        "due_date": due_date,
        "days_remaining": days_remaining,
        "learners": {
            "total": total_learners,
            "passed": passed,
            "pending": pending,
            "in_progress": in_prog,
            "failed": failed,
            "not_started": ns,
            "passed_pct": passed_pct,
            "inprog_pct": inprog_pct,
            "failed_pct": failed_pct,
            "ns_pct": ns_pct,
        },
        "departments": departments,
    }


@frappe.whitelist()
def get_question_detail(question_id):
    if not frappe.db.exists("LMS Quiz Question", question_id):
        frappe.throw("Question not found")
        
    doc = frappe.get_doc("LMS Quiz Question", question_id)
    options = []
    for opt in doc.options:
        options.append({
            "text": opt.option_text,
            "is_correct": opt.is_correct
        })
        
    return {
        "id": doc.name,
        "text": doc.question_text,
        "explanation": doc.get("explanation", ""),
        "type": doc.question_type,
        "options": options
    }


@frappe.whitelist(allow_guest=False)
def get_module_certificates(module_id):
    if not module_id:
        frappe.throw("Module ID is required")
        
    module = frappe.get_doc("LMS Module", module_id)
    
    certs = frappe.get_all(
        "LMS Certificate",
        filters={"module": module_id},
        fields=["name", "certificate_id", "user", "issued_on", "is_valid", "certificate_pdf"]
    )
    
    certificate_data = []
    for cert in certs:
        try:
            user_doc = frappe.get_doc("User", cert.user)
            status = "Issued" if cert.is_valid else "Revoked"
            
            certificate_data.append({
                "id": cert.name,
                "certificate_id": cert.certificate_id or cert.name,
                "learnerName": user_doc.full_name,
                "email": user_doc.email,
                "issueDate": str(cert.issued_on) if cert.issued_on else None,
                "expiryDate": None,
                "status": status,
                "certificate_pdf": cert.certificate_pdf or None
            })
        except Exception:
            continue
            
    template = None
    if module.enable_certificate and module.certificate_template:
        try:
            template_doc = frappe.get_doc("LMS Certificate Template", module.certificate_template)
            template = {
                "name": template_doc.template_name,
                "html": template_doc.html_template
            }
        except Exception:
            pass
    
    return {
        "template": template,
        "certificates": certificate_data,
        "course_name": module.module_name
    }


