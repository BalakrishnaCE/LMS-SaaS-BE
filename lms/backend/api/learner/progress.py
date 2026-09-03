import frappe
from frappe.utils import today, add_days, getdate, date_diff

@frappe.whitelist()
def get_learner_progress_breakdown(filter_mode="status"):
    """
    Returns progress statistics broken down by status or completion for the learner.
    """
    user = frappe.session.user

    assigned_rows = frappe.db.sql("""
        SELECT DISTINCT ma.module, ma.duration
        FROM `tabLMS Module Assignment` ma
        INNER JOIN `tabLMS Assignment User` au ON au.parent = ma.name
        INNER JOIN `tabLMS Module` m ON m.name = ma.module
        WHERE au.user = %s AND m.status = 'Published'
    """, user, as_dict=True)
    assigned_module_names = [a.module for a in assigned_rows]
    total = len(assigned_module_names)

    if not total:
        if filter_mode == "completion":
            return {
                "overallProgress": 0,
                "stats": [
                    {"label": "Highest Completion", "value": "0%"},
                    {"label": "Lowest Completion", "value": "0%"},
                    {"label": "Completed", "value": "0%"},
                    {"label": "In Progress", "value": "0%"},
                    {"label": "Not Started", "value": "0%"},
                ]
            }
        else:
            return {
                "overallProgress": 0,
                "stats": [
                    {"label": "Passed", "value": "0%"},
                    {"label": "Failed", "value": "0%"},
                    {"label": "Overdue", "value": "0%"},
                    {"label": "In Progress", "value": "0%"},
                    {"label": "Not Started", "value": "0%"},
                ]
            }

    trackers = frappe.get_all(
        "LMS Module Tracker",
        filters={"user": user, "module": ["in", assigned_module_names]},
        fields=["name", "module", "status", "progress_percentage", "started_on"]
    )
    tracker_map = {t.module: t for t in trackers}
    assignment_map = {a.module: a for a in assigned_rows}

    today_dt = getdate(today())
    counts = {
        "Passed": 0, "Failed": 0, "Overdue": 0, "In Progress": 0, "Not Started": 0,
        "Completed": 0, "Highest Completion": 0, "Lowest Completion": 0
    }

    for module_name in assigned_module_names:
        t = tracker_map.get(module_name)
        a = assignment_map.get(module_name)

        if not t:
            counts["Not Started"] += 1
            counts["Lowest Completion"] += 1 # Not started is 0% progress
            continue

        status = t.status
        progress = t.progress_percentage or 0

        if progress >= 80:
            counts["Highest Completion"] += 1
        elif progress < 30:
            counts["Lowest Completion"] += 1

        if status == "Completed":
            counts["Completed"] += 1
            # Determine pass/fail from assessment score if available
            score = frappe.db.get_value(
                "LMS Quiz Submission",
                {"user": user, "enrollment": t.name},
                "score"
            )
            passing_score = frappe.db.get_value("LMS Module", module_name, "certificate_passing_percentage") or 60
            if score is not None:
                counts["Passed" if score >= passing_score else "Failed"] += 1
            else:
                counts["Passed"] += 1
        elif status == "In Progress":
            # Check if overdue
            if a and a.duration and t.started_on:
                due_date = getdate(add_days(getdate(t.started_on), int(a.duration)))
                if due_date < today_dt:
                    counts["Overdue"] += 1
                else:
                    counts["In Progress"] += 1
            else:
                counts["In Progress"] += 1
        else:
            counts["Not Started"] += 1

    def pct(n):
        return f"{round((n / total) * 100)}%" if total else "0%"

    total_progress_percentage = sum((100 if t.status == 'Completed' else (t.progress_percentage or 0)) for t in trackers)
    overall_progress = round(total_progress_percentage / total) if total else 0

    if filter_mode == "completion":
        return {
            "overallProgress": overall_progress,
            "stats": [
                {"label": "Highest Completion", "value": pct(counts["Highest Completion"])},
                {"label": "Lowest Completion", "value": pct(counts["Lowest Completion"])},
                {"label": "Completed", "value": pct(counts["Completed"])},
                {"label": "In Progress", "value": pct(counts["In Progress"] + counts["Overdue"])},
                {"label": "Not Started", "value": pct(counts["Not Started"])},
            ]
        }
    else:
        return {
            "overallProgress": overall_progress,
            "stats": [
                {"label": "Passed", "value": pct(counts["Passed"])},
                {"label": "Failed", "value": pct(counts["Failed"])},
                {"label": "Overdue", "value": pct(counts["Overdue"])},
                {"label": "In Progress", "value": pct(counts["In Progress"])},
                {"label": "Not Started", "value": pct(counts["Not Started"])},
            ]
        }

@frappe.whitelist()
def get_learner_deadlines():
    """
    Returns upcoming deadlines for the learner.
    Driven by LMS Module Tracker and LMS Learning Path Tracker (not assignments).
    - start_date : tracker.started_on
    - duration   : LMS Module.duration or LMS Learning Path.duration (days)
    Only non-completed trackers with a duration set on the module/path are included.
    """
    user = frappe.session.user
    today_dt = getdate(today())
    results = []
    seen_ids = set()

    # ── Module Trackers ────────────────────────────────────────────────────────
    module_trackers = frappe.get_all(
        "LMS Module Tracker",
        filters={"user": user, "status": ["!=", "Completed"]},
        fields=["name", "module", "status", "started_on"]
    )

    for t in module_trackers:
        if not t.started_on or t.module in seen_ids:
            continue

        duration = frappe.get_value("LMS Module", t.module, "duration")
        if not duration:
            continue

        start = getdate(t.started_on)
        due_date = getdate(add_days(start, int(duration)))
        days_left = date_diff(due_date, today_dt)

        if days_left < -30 or days_left > 30:
            continue

        module_name = frappe.get_value("LMS Module", t.module, "module_name") or t.module
        seen_ids.add(t.module)

        results.append({
            "id": t.module,
            "title": module_name,
            "type": "module",
            "dueDate": f"Due {due_date.strftime('%b %d')}",
            "daysLeft": f"{abs(days_left)} days {'overdue' if days_left < 0 else 'left'}",
            "isOverdue": days_left < 0,
            "isUrgent": 0 <= days_left <= 3,
        })

    # ── Learning Path Trackers ─────────────────────────────────────────────────
    try:
        lp_trackers = frappe.get_all(
            "LMS Learning Path Tracker",
            filters={"user": user, "status": ["!=", "Completed"]},
            fields=["name", "learning_path", "status", "started_on"]
        )

        for t in lp_trackers:
            if not t.started_on or t.learning_path in seen_ids:
                continue

            duration = frappe.get_value("LMS Learning Path", t.learning_path, "duration")
            if not duration:
                continue

            start = getdate(t.started_on)
            due_date = getdate(add_days(start, int(duration)))
            days_left = date_diff(due_date, today_dt)

            if days_left < -30 or days_left > 30:
                continue

            path_name = frappe.get_value("LMS Learning Path", t.learning_path, "path_name") or t.learning_path
            seen_ids.add(t.learning_path)

            results.append({
                "id": t.learning_path,
                "title": path_name,
                "type": "learning_path",
                "dueDate": f"Due {due_date.strftime('%b %d')}",
                "daysLeft": f"{abs(days_left)} days {'overdue' if days_left < 0 else 'left'}",
                "isOverdue": days_left < 0,
                "isUrgent": 0 <= days_left <= 3,
            })
    except Exception:
        pass

    # Sort: overdue first, then soonest deadline
    results.sort(key=lambda x: (not x["isOverdue"], x["daysLeft"]))
    return results[:5]

@frappe.whitelist()
def update_content_progress(module, content_reference, content_type=None, status="Completed", score=None):
    user = frappe.session.user
    
    tracker = frappe.get_all(
        "LMS Module Tracker", 
        filters={"user": user, "module": module}, 
        limit=1
    )
    if not tracker:
        doc = frappe.get_doc({
            "doctype": "LMS Module Tracker",
            "user": user,
            "module": module,
            "status": "In Progress"
        })
        doc.insert(ignore_permissions=True)
        tracker_name = doc.name
    else:
        tracker_name = tracker[0].name
        
    cp = frappe.get_all(
        "LMS Content Progress",
        filters={"parent": tracker_name, "content_reference": content_reference},
        limit=1
    )
    
    if not cp:
        frappe.get_doc({
            "doctype": "LMS Content Progress",
            "parent": tracker_name,
            "parenttype": "LMS Module Tracker",
            "parentfield": "content_progress",
            "content_type": content_type or "LMS Text Content",
            "content_reference": content_reference,
            "status": status,
            "score": score
        }).insert(ignore_permissions=True)
    else:
        doc = frappe.get_doc("LMS Content Progress", cp[0].name)
        doc.status = status
        if score is not None:
            doc.score = score
        doc.save(ignore_permissions=True)
        
    tracker_doc = frappe.get_doc("LMS Module Tracker", tracker_name)
    tracker_doc.save(ignore_permissions=True)
    frappe.db.commit()
    
    return {"status": "success"}

@frappe.whitelist()
def submit_interaction_response(module, content_reference, interaction_id, interaction_type, response_data, content_type=None):
    import json
    user = frappe.session.user

    # Default content_type if not provided (backward compatibility)
    if not content_type:
        content_type = "LMS Interactive Video Content"

    # Get the tracker to link
    tracker = frappe.get_all(
        "LMS Module Tracker", 
        filters={"user": user, "module": module}, 
        limit=1
    )
    if not tracker:
        doc = frappe.get_doc({
            "doctype": "LMS Module Tracker",
            "user": user,
            "module": module,
            "status": "In Progress"
        })
        doc.insert(ignore_permissions=True)
        tracker_name = doc.name
    else:
        tracker_name = tracker[0].name

    # Load the tracker document
    tracker_doc = frappe.get_doc("LMS Module Tracker", tracker_name)

    # Get the latest attempt number for this interaction from the child table
    last_attempt = 0
    for row in tracker_doc.get("interaction_responses", []):
        if row.interactive_element == interaction_id:
            if row.attempt_number > last_attempt:
                last_attempt = row.attempt_number

    # Append a new row to keep track of every attempt
    tracker_doc.append("interaction_responses", {
        "user": user,
        "content_type": content_type,
        "content_reference": content_reference,
        "interactive_element": interaction_id,
        "interaction_type": interaction_type,
        "response_data": _serialize_response(response_data),
        "attempt_number": last_attempt + 1,
        "answered_on": frappe.utils.now_datetime()
    })
    tracker_doc.save(ignore_permissions=True)

    frappe.db.commit()
    return {"status": "success"}


def _serialize_response(response_data):
    """Always return a clean JSON string regardless of input type.
    frappeCall sends objects as JSON strings via GET params, but Frappe
    whitelisted methods may also auto-parse them back to dicts/lists.
    """
    import json as _json
    if isinstance(response_data, (dict, list)):
        return _json.dumps(response_data)
    if isinstance(response_data, str):
        try:
            _json.loads(response_data)  # already valid JSON string
            return response_data
        except (ValueError, TypeError):
            return _json.dumps(response_data)  # wrap plain string as JSON
    return _json.dumps(response_data)
