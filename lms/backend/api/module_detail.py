import frappe
import json
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

    # ── Version History ───────────────────────────────────────────────────────
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
    in_prog = sum(1 for t in trackers if t.status in ["In Progress", "Failed"])
    ns      = sum(1 for t in trackers if t.status == "Not started")
    pending = total_learners - passed

    passed_pct  = round((passed  / total_learners * 100) if total_learners else 0)
    inprog_pct  = round((in_prog / total_learners * 100) if total_learners else 0)
    ns_pct      = 100 - passed_pct - inprog_pct if total_learners else 0

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


@frappe.whitelist(allow_guest=True)
def get_assessment_analytics(module_id):
    """
    Returns assessment performance metrics for a specific module.
    """
    import re
    # Find the linked quiz for this module
    module = frappe.get_doc("LMS Module", module_id)
    if not module.final_assessments:
        return {"stats": {"passRate": 0, "averageScore": 0, "learnersRetested": 0, "retestPercentage": 0}, "missedQuestion": None, "analytics": []}
    
    quiz_name = module.final_assessments[0].assessment
    if not quiz_name:
        return {"stats": {"passRate": 0, "averageScore": 0, "learnersRetested": 0, "retestPercentage": 0}, "missedQuestion": None, "analytics": []}
    
    # Get all trackers for this module to scope the submissions
    trackers = frappe.get_all("LMS Module Tracker", filters={"module": module_id}, pluck="name")
    if not trackers:
        return {"stats": {"passRate": 0, "averageScore": 0, "learnersRetested": 0, "retestPercentage": 0}, "missedQuestion": None, "analytics": []}
        
    submissions = frappe.get_all("LMS Quiz Submission", 
        filters={"quiz": quiz_name, "enrollment": ["in", trackers]},
        fields=["name", "user", "score", "passed"]
    )
    
    if not submissions:
        return {"stats": {"passRate": 0, "averageScore": 0, "learnersRetested": 0, "retestPercentage": 0}, "missedQuestion": None, "analytics": []}

    # Aggregate stats
    user_submissions = {}
    total_score = 0
    passed_count = 0

    for sub in submissions:
        total_score += sub.score
        if sub.passed:
            passed_count += 1
            
        if sub.user not in user_submissions:
            user_submissions[sub.user] = []
        user_submissions[sub.user].append(sub)

    unique_learners = len(user_submissions)
    
    unique_passed = sum(1 for user, subs in user_submissions.items() if any(s.passed for s in subs))
    passRate = round((unique_passed / unique_learners) * 100) if unique_learners > 0 else 0
    
    averageScore = round(total_score / len(submissions)) if submissions else 0
    
    learnersRetested = sum(1 for user, subs in user_submissions.items() if len(subs) > 1)
    retestPercentage = round((learnersRetested / unique_learners) * 100) if unique_learners > 0 else 0
    
    # Question Analytics
    sub_names = [s.name for s in submissions]
    responses = frappe.get_all("LMS Quiz Response", 
        filters={"parent": ["in", sub_names]},
        fields=["question", "is_correct"]
    )
    
    question_stats = {}
    for r in responses:
        q = r.question
        if q not in question_stats:
            question_stats[q] = {"total": 0, "correct": 0}
        question_stats[q]["total"] += 1
        if r.is_correct:
            question_stats[q]["correct"] += 1
            
    analytics = []
    most_missed = None
    highest_miss_rate = -1

    if question_stats:
        questions = frappe.get_all("LMS Quiz Question", 
            filters={"name": ["in", list(question_stats.keys())]},
            fields=["name", "question_text", "question_type"]
        )
        
        for q in questions:
            stats = question_stats.get(str(q.name), {"total": 0, "correct": 0})
            pass_pct = round((stats["correct"] / stats["total"]) * 100) if stats["total"] > 0 else 0
            miss_rate = 100 - pass_pct
            
            q_type_label = "Multiple Choice"
            if q.question_type == "Single Choice":
                q_type_label = "Multiple Choice"
            elif q.question_type == "Multiple Choice":
                q_type_label = "Multiple Selection"
            elif q.question_type == "True/False":
                q_type_label = "True/False"
                
            raw_text = re.sub(r'<[^>]+>', '', q.question_text or '').strip()

            is_most_missed = False
            if miss_rate > highest_miss_rate and miss_rate > 0:
                highest_miss_rate = miss_rate
                most_missed = {
                    "id": str(q.name),
                    "text": "Most Missed Question",
                    "question": raw_text[:97] + "..." if len(raw_text) > 100 else raw_text,
                    "percentage": miss_rate
                }
                
            analytics.append({
                "id": str(q.name),
                "question": raw_text,
                "type": q_type_label,
                "passRate": pass_pct,
                "isMostMissed": False
            })
            
        if most_missed:
            for a in analytics:
                if a["id"] == most_missed["id"]:
                    a["isMostMissed"] = True

    return {
        "stats": {
            "passRate": passRate,
            "averageScore": averageScore,
            "learnersRetested": learnersRetested,
            "retestPercentage": retestPercentage
        },
        "missedQuestion": most_missed,
        "analytics": analytics
    }

@frappe.whitelist()
def get_question_detail(question_id):
    """
    Fetch question details, including text, explanation, and options.
    """
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

@frappe.whitelist()
def update_question(question_id, question_text, options, explanation=""):
    """
    Update a question's text, options, and explanation.
    `options` should be a JSON string or list of dicts: [{"text": "...", "is_correct": 1/0}]
    """
    import json
    if isinstance(options, str):
        options = json.loads(options)
        
    doc = frappe.get_doc("LMS Quiz Question", question_id)
    doc.question_text = question_text
    doc.explanation = explanation
    
    # Clear existing options
    doc.set("options", [])
    
    # Add new options
    for opt in options:
        doc.append("options", {
            "option_text": opt.get("text"),
            "is_correct": opt.get("is_correct", 0)
        })
        
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return "success"

@frappe.whitelist()
def delete_question(quiz_name, question_id):
    """
    Remove a question from a quiz and delete the question entirely.
    """
    # 1. Remove from quiz
    if frappe.db.exists("LMS Quiz", quiz_name):
        quiz = frappe.get_doc("LMS Quiz", quiz_name)
        new_questions = [q for q in quiz.questions if str(q.quiz_question) != str(question_id)]
        quiz.set("questions", new_questions)
        quiz.save(ignore_permissions=True)
        
    # 2. Delete question (and its responses if necessary, though Frappe handles linked docs based on rules)
    # Delete related responses first to avoid foreign key constraints
    frappe.db.sql("DELETE FROM `tabLMS Quiz Response` WHERE question=%s", (question_id,))
    
    frappe.delete_doc("LMS Quiz Question", question_id, ignore_permissions=True, force=1)
    frappe.db.commit()
    return "success"

@frappe.whitelist(allow_guest=False)
def update_module_settings(module_id, settings):
    """
    Updates the settings of an LMS Module.
    `settings` should be a JSON string of boolean/integer fields.
    """
    import json
    if not frappe.has_permission("LMS Module", "write", doc=module_id):
        frappe.throw("Not permitted", frappe.PermissionError)
        
    module = frappe.get_doc("LMS Module", module_id)
    
    try:
        settings_dict = json.loads(settings)
        
        for key, value in settings_dict.items():
            if module.meta.has_field(key):
                module.db_set(key, 1 if value else 0)
                
        return {"message": "success"}

    except Exception as e:
        frappe.log_error(f"Error in update_module_settings: {str(e)}")
        return {"error": str(e)}

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
            
    # For now, just return a dummy template name if any certificates exist
    # A real implementation would fetch the template assigned to the module
    template = {"name": "Default Template"} if certificate_data else None
    
    return {
        "template": template,
        "certificates": certificate_data,
        "course_name": module.module_name
    }

@frappe.whitelist(allow_guest=False)
def create_module_version(module_id, description=""):
    """
    Creates a new version in the module's version history.
    Sets all existing versions' 'is_current' to 0 and adds a new version.
    """
    module = frappe.get_doc("LMS Module", module_id)
    
    # Reset is_current on all existing versions
    version_history = module.get("version_history", [])
    for v in version_history:
        v.is_current = 0
        
    # Calculate new version number (e.g. v1.0, v1.1, etc.)
    if not version_history:
        new_version = "v1.0"
    else:
        try:
            last_ver = str(version_history[-1].version).lstrip('vV')
            parts = last_ver.split('.')
            if len(parts) == 2:
                new_version = f"v{int(parts[0])}.{int(parts[1]) + 1}"
            else:
                new_version = f"v{int(float(last_ver)) + 1}.0"
        except Exception:
            new_version = f"v{len(version_history) + 1}.0"
            
    module.append("version_history", {
        "version": new_version,
        "is_current": 1,
        "description": description,
        "date": today(),
        "author": frappe.session.user
    })
    
    module.save(ignore_permissions=True)
    return {"message": "success", "new_version": new_version}
