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

    # ── Step 1: resolve all assigned users from LMS Module Assignment ──────
    assignments = frappe.get_all(
        "LMS Module Assignment",
        filters={"module": module_id},
        fields=["name", "assignment_type", "duration", "creation"]
    )

    assigned_users = {}  # user -> {duration, creation}
    for a in assignments:
        duration = a.duration or 0
        creation_date = a.creation
        if a.assignment_type == "Everyone":
            lms_roles = frappe.get_all("Has Role", filters={"role": ["in", ["LMS-Learner", "LMS-TL"]]}, fields=["parent"])
            valid_users = [r.parent for r in lms_roles if r.parent not in ["Administrator", "Guest"]]
            
            all_users = frappe.get_all(
                "User",
                filters={"enabled": 1, "name": ["in", valid_users] if valid_users else ["in", ["__nobody__"]]},
                fields=["name"]
            )
            for u in all_users:
                if u.name not in assigned_users:
                    assigned_users[u.name] = {"duration": duration, "creation": creation_date}
        elif a.assignment_type == "Manual":
            learners = frappe.get_all("LMS Assignment User", filters={"parent": a.name}, fields=["user"])
            for l in learners:
                if l.user not in assigned_users:
                    assigned_users[l.user] = {"duration": duration, "creation": creation_date}
        else:  # Team
            teams = frappe.get_all("LMS Assignment Team", filters={"parent": a.name}, fields=["team"])
            for t in teams:
                members = frappe.get_all("LMS Team Member", filters={"parent": t.team}, fields=["user"])
                for m in members:
                    if m.user not in assigned_users:
                        assigned_users[m.user] = {"duration": duration, "creation": creation_date}

    # ── Step 2: fetch tracker data for users who have started ───────────────
    trackers = frappe.get_all(
        "LMS Module Tracker",
        filters={"module": module_id},
        fields=["status", "user", "total_score", "started_on", "creation"]
    )
    tracker_map = {t.user: t for t in trackers}

    # ── Step 3: merge — use assigned_users as the source of truth ───────────
    # If there are no assignment records, fall back to tracker-only (legacy behaviour)
    if assigned_users:
        all_user_keys = list(assigned_users.keys())
    else:
        all_user_keys = [t.user for t in trackers if t.user]

    total_learners = len(all_user_keys)
    passed   = 0
    in_prog  = 0
    failed   = 0
    ns       = 0

    for user in all_user_keys:
        t = tracker_map.get(user)
        if t is None:
            ns += 1
        elif t.status == "Completed":
            passed += 1
        elif t.status == "In Progress":
            in_prog += 1
        elif t.status == "Failed":
            failed += 1
        else:
            ns += 1

    pending = total_learners - passed

    passed_pct  = round((passed  / total_learners * 100) if total_learners else 0)
    inprog_pct  = round((in_prog / total_learners * 100) if total_learners else 0)
    failed_pct  = round((failed / total_learners * 100) if total_learners else 0)
    ns_pct      = max(0, 100 - passed_pct - inprog_pct - failed_pct) if total_learners else 0

    # ── Step 4: department breakdown (based on all assigned users) ──────────
    user_emails = list(set(all_user_keys))
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
    for user in all_user_keys:
        dept = dept_map.get(user, "Unknown")
        t = tracker_map.get(user)
        if dept not in dept_stats:
            dept_stats[dept] = {"total": 0, "passed": 0, "pending": 0}
        dept_stats[dept]["total"] += 1
        if t and t.status == "Completed":
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
    
    validity_days = module.certificate_validity_period or 0
    
    certificate_data = []
    for cert in certs:
        try:
            user_doc = frappe.get_doc("User", cert.user)
            status = "Issued" if cert.is_valid else "Revoked"
            
            expiry_date = None
            if cert.issued_on and validity_days > 0:
                expiry_date = frappe.utils.add_days(cert.issued_on, validity_days)
            
            certificate_data.append({
                "id": cert.name,
                "certificate_id": cert.certificate_id or cert.name,
                "learnerName": user_doc.full_name,
                "email": user_doc.email,
                "issueDate": str(cert.issued_on) if cert.issued_on else None,
                "expiryDate": str(expiry_date) if expiry_date else None,
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

def get_all_assigned_modules_for_learner(user):
    """
    Returns a list of dicts: [{"module": "Mod1", "duration": 10, "is_mandatory": 1, "creation": ...}]
    Resolves Manual, Team, and Everyone assignments for the given user.
    Only includes Published modules.
    """
    assigned_modules = {}

    user_roles = frappe.get_all("Has Role", filters={"parent": user}, fields=["role"])
    role_names = [r.role for r in user_roles]
    is_learner_or_tl = ("LMS-Learner" in role_names or "LMS-TL" in role_names)
    is_admin_or_guest = ("Administrator" in role_names or "Guest" in role_names)
    qualifies_for_everyone = is_learner_or_tl and not is_admin_or_guest

    # 1. Manual
    manual_rows = frappe.db.sql("""
        SELECT ma.module, ma.duration, ma.is_mandatory, ma.creation
        FROM `tabLMS Module Assignment` ma
        INNER JOIN `tabLMS Assignment User` au ON au.parent = ma.name
        WHERE au.user = %s AND ma.assignment_type = 'Manual'
    """, user, as_dict=True)
    for row in manual_rows:
        if row.module not in assigned_modules:
            assigned_modules[row.module] = row

    # 2. Team
    team_rows = frappe.db.sql("""
        SELECT ma.module, ma.duration, ma.is_mandatory, ma.creation
        FROM `tabLMS Module Assignment` ma
        INNER JOIN `tabLMS Assignment Team` at ON at.parent = ma.name
        INNER JOIN `tabLMS Team Member` tm ON tm.parent = at.team
        WHERE tm.user = %s AND ma.assignment_type = 'Team'
    """, user, as_dict=True)
    for row in team_rows:
        if row.module not in assigned_modules:
            assigned_modules[row.module] = row

    # 3. Everyone
    if qualifies_for_everyone:
        everyone_rows = frappe.db.sql("""
            SELECT ma.module, ma.duration, ma.is_mandatory, ma.creation
            FROM `tabLMS Module Assignment` ma
            WHERE ma.assignment_type = 'Everyone'
        """, as_dict=True)
        for row in everyone_rows:
            if row.module not in assigned_modules:
                assigned_modules[row.module] = row

    published_modules = set([
        m.name for m in frappe.get_all("LMS Module", filters={"status": "Published"}, fields=["name"])
    ])

    final_list = []
    for mod, data in assigned_modules.items():
        if mod in published_modules:
            final_list.append(data)
            
    return final_list
