import frappe
from frappe.utils import today, add_days, getdate

@frappe.whitelist(allow_guest=True)
def get_department_performance():
    user = frappe.session.user
    roles = frappe.get_roles(user)
    
    # Check TL/Manager role first so it takes precedence over System Manager
    if "LMS-TL" in roles or "LMS Manager" in roles:
        lead_rows = frappe.get_all("LMS Team Lead", filters={"user": user, "parenttype": "LMS Team"}, fields=["parent"])
        team_names = list({r.parent for r in lead_rows})
        if not team_names:
            return []
        teams = frappe.get_all("LMS Team", filters={"name": ["in", team_names]}, fields=["name", "team_name"])
    elif "System Manager" in roles or "LMS Admin" in roles:
        teams = frappe.get_all("LMS Team", fields=["name", "team_name"])
    else:
        return []
        
    assignments = frappe.get_all("LMS Module Assignment", fields=["module", "duration"])
    assignment_map = {a.module: a for a in assignments}
    today_dt = getdate(today())
    
    results = []
    for t in teams:
        members = frappe.get_all("LMS Team Member", filters={"parent": t.name, "parentfield": "learners"}, fields=["user"])
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
        
        completed_trackers = [tr for tr in trackers if tr.status == "Completed" and tr.total_score is not None and tr.total_score >= 0]
        avg_score = sum([tr.total_score for tr in completed_trackers]) / len(completed_trackers) if len(completed_trackers) > 0 else None
        
        results.append({
            "name": t.team_name,
            "completionRate": c_rate,
            "avgScore": int(avg_score) if avg_score is not None else None,
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

    assignments = frappe.get_all("LMS Module Assignment", fields=["module", "duration", "is_mandatory"], limit_page_length=0)
    assignment_map = {a.module: a for a in assignments}
    today_dt = getdate(today())

    # 1. Learners at risk
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
            "type": "risk",
            "title": f"{data['count']} learner{'s' if data['count'] > 1 else ''} are at risk",
            "description": f"{data['count']} learner{'s' if data['count'] > 1 else ''} have not completed their assigned {mandatory_text} '{module_name}' module.",
            "count": data['count']
        })
        
    results.sort(key=lambda x: x["count"], reverse=True)

    # 2. Pending QA Evaluations
    qa_submissions = frappe.get_all(
        "LMS Quiz Submission",
        filters={"user": ["in", member_emails]},
        fields=["name", "user", "quiz", "enrollment", "submitted_on", "score"]
    )
    
    pending_qa = []
    for sub in qa_submissions:
        if sub.score is None or sub.score == 0.0:
            eval_method = frappe.get_value("LMS Quiz", sub.quiz, "evaluation_method")
            if eval_method == "Manual review":
                # Verify the quiz actually has questions requiring human evaluation
                # (Scenario Based or open-ended Fill in the Blank)
                has_manual_questions = frappe.db.sql("""
                    SELECT COUNT(*) 
                    FROM `tabLMS Quiz Question` q
                    JOIN `tabLMS Quiz Child` c ON c.quiz_question = q.name
                    WHERE c.parent = %(quiz)s
                    AND (
                        q.question_type = 'Scenario Based'
                        OR (q.question_type = 'Fill in the Blank' AND NOT EXISTS (
                            SELECT 1 FROM `tabLMS Quiz Option` o WHERE o.parent = q.name LIMIT 1
                        ))
                    )
                """, {"quiz": sub.quiz})[0][0]
                
                if not has_manual_questions:
                    continue

                learner_name = frappe.get_value("User", sub.user, "full_name") or sub.user
                quiz_title = frappe.get_value("LMS Quiz", sub.quiz, "title") or sub.quiz
                
                due_date = add_days(getdate(sub.submitted_on), 3) if sub.submitted_on else add_days(today_dt, 3)
                
                pending_qa.append({
                    "learner": learner_name,
                    "quiz_title": quiz_title,
                    "due_date": due_date.strftime("%b %d, %Y"),
                    "submission_id": sub.name,
                    "sort_date": getdate(due_date)
                })
    
    if pending_qa:
        pending_qa.sort(key=lambda x: x["sort_date"])
        
        if len(pending_qa) == 1:
            first = pending_qa[0]
            description = f"A manual QA assessment for '{first['quiz_title']}' was submitted by {first['learner']} and requires your evaluation."
            title = "Pending QA Evaluation"
        else:
            first_due = pending_qa[0]
            days_left = (first_due["sort_date"] - today_dt).days
            if days_left < 0:
                description = f"Assessment overdue by {abs(days_left)} days"
            elif days_left == 0:
                description = "Assessment due today"
            else:
                description = f"Assessment due in {days_left} days"
            title = f"{len(pending_qa)} Pending QA Evaluation{'s' if len(pending_qa) > 1 else ''}"
            
        # Insert at the top of the list because it's high priority
        results.insert(0, {
            "type": "qa",
            "title": title,
            "description": description,
            "count": len(pending_qa),
            "submissions": pending_qa
        })

    return results[:5]

@frappe.whitelist()
def get_manager_modules():
    from lms.backend.api.learner.dashboard import (
        get_module_category,
        get_path_category,
        get_path_duration_str,
        get_all_assigned_paths_for_learner,
    )
    from lms.backend.api.learner.tracker_sync import sync_missing_trackers
    from lms.backend.api.common.module_detail import (
        get_all_assigned_modules_for_learner,
        get_estimated_hours_from_curriculum,
    )
    
    tl_user = frappe.session.user
    sync_missing_trackers(tl_user)
    
    assigned_rows = get_all_assigned_modules_for_learner(tl_user)
    today_dt = frappe.utils.getdate(frappe.utils.today())

    results = []
    
    # 1. Modules
    for a in assigned_rows:
        module_id = a.get("module") if isinstance(a, dict) else a.module
        is_mandatory = bool(a.get("is_mandatory") if isinstance(a, dict) else a.is_mandatory)
        a_duration = a.get("duration") if isinstance(a, dict) else getattr(a, "duration", None)
        
        module_doc = frappe.get_value(
            "LMS Module",
            module_id,
            ["module_name", "status", "image"],
            as_dict=True
        )
        if not module_doc or module_doc.status != 'Published':
            continue

        # Skip modules that have been explicitly unassigned (Unassigned sentinel)
        if frappe.db.exists("LMS Module Tracker", {"user": tl_user, "module": module_id, "status": "Unassigned"}):
            continue

        # Calculate manager's personal completion for this module
        trackers = frappe.get_all(
            "LMS Module Tracker",
            filters={"user": tl_user, "module": module_id, "status": ["!=", "Unassigned"]},
            fields=["status", "progress_percentage", "started_on", "is_saved"],
            order_by="modified desc"
        )
        
        total_items = frappe.db.count("LMS Module Lesson Child", {"parent": module_id})
        
        days_left = None
        is_overdue = False
        if trackers and trackers[0].started_on and a_duration:
            start = frappe.utils.getdate(trackers[0].started_on)
            due_date = frappe.utils.getdate(frappe.utils.add_days(start, int(a_duration)))
            days_left = frappe.utils.date_diff(due_date, today_dt)
            is_overdue = days_left < 0

        if trackers:
            t = trackers[0]
            percent = 100 if t.status == "Completed" else (t.progress_percentage or 0)
            completed = round(total_items * (percent / 100))
            if percent == 100 or (t.status and t.status.lower() == "completed"):
                status = "Completed"
            elif percent > 0 or (t.status and t.status.lower() == "in progress"):
                status = "In Progress"
            else:
                status = "Not started"
            is_saved = bool(t.is_saved)
        else:
            completed = 0
            percent = 0
            status = "Not started"
            is_saved = False
            
        from lms.backend.api.common.module_detail import get_module_duration_mins, format_duration_str
        total_mins = get_module_duration_mins(module_id)
        if total_mins > 0:
            duration_str = format_duration_str(total_mins)
        else:
            est_hours = get_estimated_hours_from_curriculum(module_id)
            if est_hours > 0:
                if est_hours < 1:
                    duration_str = f"{int(est_hours * 60)} min"
                else:
                    duration_str = f"{est_hours:g} hr"
            else:
                duration_str = "0 min"
            
        results.append({
            "id": module_id,
            "title": module_doc.module_name,
            "category": get_module_category(module_id),
            "type": "Module",
            "lessonsCount": total_items,
            "duration": duration_str,
            "daysLeft": days_left,
            "isOverdue": is_overdue,
            "completionRate": percent,
            "completedCount": completed,
            "totalCount": total_items,
            "status": status,
            "isRequired": is_mandatory,
            "image": module_doc.image,
            "isSaved": is_saved,
            "completion": {
                "current": completed,
                "total": total_items if total_items > 0 else 1,
                "percent": percent
            },
            "isMandatory": is_mandatory,
            "thumbnail": module_doc.image,
            "creation": a.get("creation", "") if isinstance(a, dict) else getattr(a, "creation", ""),
        })
        
    # 2. Learning Paths
    assigned_paths = get_all_assigned_paths_for_learner(tl_user)
    for p in assigned_paths:
        path_id = p.get("learning_path") if isinstance(p, dict) else p.learning_path
        is_mandatory = bool(p.get("is_mandatory") if isinstance(p, dict) else p.is_mandatory)
        p_duration = p.get("duration") if isinstance(p, dict) else getattr(p, "duration", None)
        
        path_doc = frappe.get_value(
            "LMS Learning Path",
            path_id,
            ["path_name", "status", "image"],
            as_dict=True
        )
        if not path_doc or path_doc.status != 'Published':
            continue

        if frappe.db.exists("LMS Learning Path Tracker", {"user": tl_user, "learning_path": path_id, "status": "Unassigned"}):
            continue

        lp_trackers = frappe.get_all(
            "LMS Learning Path Tracker",
            filters={"user": tl_user, "learning_path": path_id, "status": ["!=", "Unassigned"]},
            fields=["status", "progress_percentage", "started_on", "is_saved"],
            order_by="modified desc"
        )
        
        total_items = frappe.db.count("LMS Learning Path Course", {"parent": path_id})
        
        days_left = None
        is_overdue = False
        if lp_trackers and lp_trackers[0].started_on and p_duration:
            start = frappe.utils.getdate(lp_trackers[0].started_on)
            due_date = frappe.utils.getdate(frappe.utils.add_days(start, int(p_duration)))
            days_left = frappe.utils.date_diff(due_date, today_dt)
            is_overdue = days_left < 0

        if lp_trackers:
            lpt = lp_trackers[0]
            percent = 100 if lpt.status == "Completed" else (lpt.progress_percentage or 0)
            completed = round(total_items * (percent / 100))
            if percent == 100 or (lpt.status and lpt.status.lower() == "completed"):
                status = "Completed"
            elif percent > 0 or (lpt.status and lpt.status.lower() == "in progress"):
                status = "In Progress"
            else:
                status = "Not started"
            is_saved = bool(lpt.is_saved)
        else:
            completed = 0
            percent = 0
            status = "Not started"
            is_saved = False

        results.append({
            "id": path_id,
            "title": path_doc.path_name,
            "category": get_path_category(path_id),
            "type": "Path",
            "lessonsCount": total_items,
            "modulesCount": total_items,
            "duration": get_path_duration_str(path_id),
            "daysLeft": days_left,
            "isOverdue": is_overdue,
            "completionRate": percent,
            "completedCount": completed,
            "totalCount": total_items,
            "status": status,
            "isRequired": is_mandatory,
            "image": path_doc.image,
            "isSaved": is_saved,
            "completion": {
                "current": completed,
                "total": total_items if total_items > 0 else 1,
                "percent": percent
            },
            "isMandatory": is_mandatory,
            "thumbnail": path_doc.image,
            "creation": p.get("creation", "") if isinstance(p, dict) else getattr(p, "creation", ""),
        })
        
    # Sort results:
    # 1. Started modules & paths ("Continue Learning") first
    # 2. Highest completionRate first
    # 3. Creation date (newest first)
    def sort_key(x):
        is_started = 1 if (x.get("status") and x.get("status").lower() != "not started") else 0
        progress = x.get("completionRate") or 0
        creation = str(x.get("creation") or "")
        return (is_started, progress, creation)

    results.sort(key=sort_key, reverse=True)

    return results

@frappe.whitelist()
def get_manager_teams():
    user = frappe.session.user
    roles = frappe.get_roles(user)

    if ("LMS-TL" in roles or "LMS Manager" in roles) and not ("LMS-Admin" in roles or "LMS Admin" in roles):
        user_identifiers = {user}
        try:
            user_info = frappe.db.get_value("User", user, ["name", "email"], as_dict=True)
            if user_info:
                if user_info.get("name"):
                    user_identifiers.add(user_info["name"])
                if user_info.get("email"):
                    user_identifiers.add(user_info["email"])
        except Exception:
            pass

        lead_rows = frappe.get_all(
            "LMS Team Lead",
            filters={"user": ["in", list(user_identifiers)], "parenttype": "LMS Team"},
            fields=["parent"],
        )
        team_names = list({r.parent for r in lead_rows})
        if not team_names:
            return []
        teams = frappe.get_all("LMS Team", filters={"name": ["in", team_names]}, fields=["name", "team_name"])
    elif "System Manager" in roles or "LMS Admin" in roles or "LMS-Admin" in roles:
        teams = frappe.get_all("LMS Team", fields=["name", "team_name"])
    else:
        return []

    for team in teams:
        learner_count = frappe.db.count("LMS Team Member", {"parent": team.name, "parenttype": "LMS Team"})
        team.learner_count = learner_count

    return teams

