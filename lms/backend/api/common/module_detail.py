import frappe
from frappe.utils import today, add_days, getdate, now

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
    in_prog = sum(1 for t in trackers if t.status in ["In Progress", "Failed"])
    ns      = sum(1 for t in trackers if t.status == "Not started")
    pending = total_learners - passed

    passed_pct  = round((passed  / total_learners * 100) if total_learners else 0)
    inprog_pct  = round((in_prog / total_learners * 100) if total_learners else 0)
    ns_pct      = 100 - passed_pct - inprog_pct if total_learners else 0

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

    estimated_hours = None
    try:
        lesson_names = [l.lesson for l in module.get("lessons", []) if l.lesson]
        if lesson_names:
            lesson_docs = frappe.get_all("LMS Lesson", filters={"name": ["in", lesson_names]}, fields=["estimated_time"])
            total_mins = sum((l.estimated_time or 0) for l in lesson_docs)
            estimated_hours = round(total_mins / 60, 1) if total_mins else None
    except Exception:
        pass

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
            "not_started": ns,
            "passed_pct": passed_pct,
            "inprog_pct": inprog_pct,
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
        fields=["name", "certificate_id", "user", "issued_on", "is_valid"]
    )
    
    certificate_data = []
    for cert in certs:
        try:
            user_doc = frappe.get_doc("User", cert.user)
            status = "Issued" if cert.is_valid else "Revoked"
            
            certificate_data.append({
                "id": cert.name,
                "learnerName": user_doc.full_name,
                "email": user_doc.email,
                "issueDate": str(cert.issued_on) if cert.issued_on else None,
                "expiryDate": None,
                "status": status
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
