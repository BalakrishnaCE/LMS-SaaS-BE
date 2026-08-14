import frappe
from frappe.utils import today, add_days, getdate, now

@frappe.whitelist(allow_guest=True)
def get_module_overview(module_id):
    """
    Returns all data needed to render the Module Detail Overview tab:
    - module metadata
    - learner progress stats & completion breakdown
    - department performance rows
    - due date / assignment info
    """
    module = frappe.get_doc("LMS Module", module_id)

    # ── Categories ────────────────────────────────────────────────────────────
    categories = [c.category for c in (module.category or [])]

    # ── Lessons count ─────────────────────────────────────────────────────────
    lesson_count = len(module.get("lessons", []))

    # ── Assignment info ───────────────────────────────────────────────────────
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

    # ── Trackers ──────────────────────────────────────────────────────────────
    trackers = frappe.get_all(
        "LMS Module Tracker",
        filters={"module": module_id},
        fields=["status", "user", "total_score", "started_on", "creation"]
    )

    total_learners = len(trackers)
    passed  = sum(1 for t in trackers if t.status == "Completed")
    in_prog = sum(1 for t in trackers if t.status == "In Progress")
    pending = total_learners - passed

    passed_pct  = round((passed  / total_learners * 100) if total_learners else 0)
    inprog_pct  = round((in_prog / total_learners * 100) if total_learners else 0)
    ns          = max(total_learners - passed - in_prog, 0)
    ns_pct      = 100 - passed_pct - inprog_pct

    # ── Department performance ────────────────────────────────────────────────
    # Get user → dept mapping
    user_emails = list({t.user for t in trackers if t.user})

    # Build dept → learner set
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

    # ── Estimated duration ────────────────────────────────────────────────────
    # Sum up estimated_time from all linked lessons
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
            "is_mandatory": module.is_mandatory,
            "version": getattr(module, "version", "1.0"),
            "categories": categories,
            "lesson_count": lesson_count,
            "estimated_hours": estimated_hours,
            "created_by": module.owner,
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


@frappe.whitelist(allow_guest=True)
def get_ai_insights(module_id):
    """
    Returns AI-generated insights for a module.
    Currently generates heuristic-based insights from real tracker data.
    """
    trackers = frappe.get_all(
        "LMS Module Tracker",
        filters={"module": module_id},
        fields=["status", "user", "total_score", "started_on", "completed_on"]
    )

    total = len(trackers)
    if total == 0:
        return {"insights": [
            "No learner data yet. Assign this module to learners to see insights."
        ]}

    completed = [t for t in trackers if t.status == "Completed"]
    in_prog   = [t for t in trackers if t.status == "In Progress"]
    not_started = total - len(completed) - len(in_prog)

    insights = []

    # Completion rate insight
    completion_rate = round(len(completed) / total * 100)
    if completion_rate >= 80:
        insights.append(f"{completion_rate}% of learners have completed this module — excellent engagement!")
    elif completion_rate >= 50:
        insights.append(f"{completion_rate}% completion rate. Consider sending a reminder to the remaining learners.")
    else:
        insights.append(f"Only {completion_rate}% completion rate. This module may need attention — consider reviewing its difficulty or length.")

    # Score insight
    scores = [t.total_score for t in completed if t.total_score is not None]
    if scores:
        avg_score = round(sum(scores) / len(scores))
        if avg_score < 60:
            insights.append(f"Average assessment score is {avg_score}% — learners may be struggling with the content.")
        elif avg_score >= 85:
            insights.append(f"Strong average assessment score of {avg_score}% among completions.")
        else:
            insights.append(f"Average assessment score is {avg_score}%.")

    # Not started
    if not_started > 0:
        insights.append(f"{not_started} learner{'s' if not_started > 1 else ''} haven't started yet. A nudge notification could help.")

    # In progress but no score
    stalled = [t for t in in_prog if not t.total_score]
    if len(stalled) > 0:
        insights.append(f"{len(stalled)} learner{'s' if len(stalled) > 1 else ''} started but haven't completed any assessments.")

    return {"insights": insights[:4]}  # cap at 4
