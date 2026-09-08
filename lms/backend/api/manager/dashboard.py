import frappe
from frappe.utils import today, add_days, getdate

@frappe.whitelist(allow_guest=True)
def get_department_performance():
    teams = frappe.get_all("LMS Team", fields=["name", "team_name"])
    
    assignments = frappe.get_all("LMS Module Assignment", fields=["module", "duration"])
    assignment_map = {a.module: a for a in assignments}
    today_dt = getdate(today())
    
    results = []
    for t in teams:
        members = frappe.get_all("LMS Team Member", filters={"parent": t.name}, fields=["user"])
        member_emails = [m.user for m in members]
        
        if not member_emails:
            continue
            
        trackers = frappe.get_all("LMS Module Tracker", filters={"user": ["in", member_emails]}, fields=["user", "status", "total_score", "module", "started_on", "creation"])
        total_t = len(trackers)
        completed = len([tr for tr in trackers if tr.status == "Completed"])
        
        overdue_users = set()
        for tr in trackers:
            if tr.status != "Completed" and tr.started_on:
                a = assignment_map.get(tr.module)
                if a and a.duration:
                    due = getdate(add_days(getdate(tr.started_on), a.duration))
                    if due < today_dt:
                        overdue_users.add(tr.user)
        
        c_rate = int((completed / total_t) * 100) if total_t > 0 else 0
        
        completed_trackers = [tr for tr in trackers if tr.status == "Completed" and tr.total_score is not None]
        avg_score = sum([tr.total_score for tr in completed_trackers]) / len(completed_trackers) if len(completed_trackers) > 0 else 0
        
        results.append({
            "name": t.team_name,
            "completionRate": c_rate,
            "avgScore": int(avg_score),
            "overdueLearners": len(overdue_users),
            "criticalOverdue": len(overdue_users) > 5
        })
    return results

@frappe.whitelist()
def get_needs_attention():
    from lms.backend.api.manager.metrics import _get_team_member_emails
    tl_user = frappe.session.user
    member_emails = _get_team_member_emails(tl_user)

    if not member_emails:
        return []

    assignments = frappe.get_all("LMS Module Assignment", fields=["module", "duration", "is_mandatory"])
    assignment_map = {a.module: a for a in assignments}
    today_dt = getdate(today())

    trackers = frappe.get_all(
        "LMS Module Tracker",
        filters={"user": ["in", member_emails], "status": ["!=", "Completed"]},
        fields=["user", "module", "started_on", "status"]
    )

    overdue_by_module = {}
    
    for t in trackers:
        if t.started_on:
            a = assignment_map.get(t.module)
            if a and a.duration:
                due = add_days(getdate(t.started_on), a.duration)
                if getdate(due) < today_dt:
                    if t.module not in overdue_by_module:
                        overdue_by_module[t.module] = {"count": 0, "mandatory": a.is_mandatory}
                    overdue_by_module[t.module]["count"] += 1

    results = []
    for mod, data in overdue_by_module.items():
        module_name = frappe.get_value("LMS Module", mod, "module_name") or mod
        mandatory_text = "mandatory" if data["mandatory"] else "optional"
        results.append({
            "title": f"{data['count']} learner{'s' if data['count'] > 1 else ''} at risk",
            "description": f"{data['count']} learner{'s' if data['count'] > 1 else ''} have not completed their assigned {mandatory_text} '{module_name}' module.",
            "count": data['count']
        })
        
    results.sort(key=lambda x: x["count"], reverse=True)
    return results[:5]

@frappe.whitelist()
def get_manager_modules():
    from lms.backend.api.manager.metrics import _get_team_member_emails
    from lms.backend.api.learner.dashboard import get_module_category
    
    tl_user = frappe.session.user
    member_emails = _get_team_member_emails(tl_user)
    
    if not member_emails:
        return []

    # Get all assignments for team members
    assignments = frappe.db.sql("""
        SELECT DISTINCT ma.module, ma.is_mandatory, ma.duration
        FROM `tabLMS Module Assignment` ma
        INNER JOIN `tabLMS Assignment User` au ON au.parent = ma.name
        WHERE au.user IN %(members)s
    """, {"members": member_emails}, as_dict=True)

    results = []
    
    for a in assignments:
        module_doc = frappe.get_value(
            "LMS Module",
            a.module,
            ["module_name", "status", "image"],
            as_dict=True
        )
        if not module_doc or module_doc.status != 'Published':
            continue

        # Calculate team completion for this module
        trackers = frappe.get_all(
            "LMS Module Tracker",
            filters={"user": ["in", member_emails], "module": a.module},
            fields=["status"]
        )
        
        total_assigned = len(trackers)
        completed = len([t for t in trackers if t.status == "Completed"])
        percent = int((completed / total_assigned) * 100) if total_assigned > 0 else 0
        
        from lms.backend.api.common.module_detail import get_estimated_hours_from_curriculum
        est_hours = get_estimated_hours_from_curriculum(a.module)
        if est_hours > 0:
            if est_hours < 1:
                duration_str = f"{int(est_hours * 60)} min"
            else:
                duration_str = f"{est_hours:g} hr"
        else:
            duration_str = "0 min"
            
        results.append({
            "id": a.module,
            "title": module_doc.module_name,
            "category": get_module_category(a.module),
            "type": "Module",
            "lessonsCount": frappe.db.count("LMS Module Lesson Child", {"parent": a.module}),
            "duration": duration_str,
            "completion": {
                "current": completed,
                "total": total_assigned,
                "percent": percent
            },
            "isMandatory": bool(a.is_mandatory),
            "thumbnail": module_doc.image,
        })
        
    return results
