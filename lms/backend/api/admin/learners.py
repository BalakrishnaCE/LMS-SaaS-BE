import frappe
from frappe import _
from frappe.utils import get_url, add_days, today, getdate

def _evaluate_user_risks(users):
    if not users:
        return {}
        
    user_names = [u.name for u in users]

    modules = frappe.get_all("LMS Module", fields=["name", "duration", "is_mandatory"])
    modules_dict = {m.name: m for m in modules}

    trackers = frappe.get_all("LMS Module Tracker", filters={"user": ("in", user_names)}, fields=["name", "user", "module", "status", "progress_percentage", "started_on", "creation", "modified"])
    submissions = frappe.get_all("LMS Quiz Submission", filters={"user": ("in", user_names)}, fields=["name", "user", "quiz", "passed", "creation"], order_by="creation desc")
    
    user_trackers = {u: [] for u in user_names}
    for t in trackers:
        user_trackers[t.user].append(t)
        
    user_submissions = {u: [] for u in user_names}
    for s in submissions:
        user_submissions[s.user].append(s)

    current_date = getdate(today())
    fourteen_days_ago = add_days(today(), -14)
    
    user_evals = {}
    
    for u in users:
        u_trackers = user_trackers[u.name]
        u_submissions = user_submissions[u.name]
        
        assigned = len(u_trackers)
        completed = sum(1 for t in u_trackers if t.status == "Completed")
        failed = sum(1 for t in u_trackers if t.status == "Failed")
        
        total_progress = 0
        for t in u_trackers:
            if t.status == "Completed":
                total_progress += 100
            else:
                total_progress += float(t.progress_percentage or 0)
        
        avg_progress = total_progress / assigned if assigned > 0 else 0
        
        mandatory_overdue_count = 0
        last_activity_date = None
        next_deadline = None
        
        for t in u_trackers:
            if not last_activity_date or getdate(t.modified) > getdate(last_activity_date):
                last_activity_date = t.modified
            
            module = modules_dict.get(t.module)
            if module and t.status != "Completed":
                start_date = t.started_on or t.creation
                if start_date and module.duration:
                    due_date = getdate(add_days(start_date, module.duration))
                    
                    if module.is_mandatory and current_date > due_date:
                        mandatory_overdue_count += 1
                        
                    if not next_deadline or due_date < next_deadline:
                        next_deadline = due_date
                        
        no_activity_14_days = False
        if last_activity_date and getdate(last_activity_date) < getdate(fourteen_days_ago):
            no_activity_14_days = True
            
        latest_failed_twice = False
        score_below_pass = False
        
        if u_submissions:
            latest_sub = u_submissions[0]
            if latest_sub.passed == 0:
                score_below_pass = True
            
            quiz_fails = {}
            for sub in u_submissions:
                if sub.passed == 0:
                    quiz_fails[sub.quiz] = quiz_fails.get(sub.quiz, 0) + 1
                    if quiz_fails[sub.quiz] >= 2:
                        latest_failed_twice = True
                        break
                else:
                    quiz_fails[sub.quiz] = 0
                    
        risk_factors = []
        learner_risk = "On Track"
        
        if mandatory_overdue_count >= 2 or no_activity_14_days or latest_failed_twice:
            learner_risk = "Overdue"
            if mandatory_overdue_count >= 2:
                risk_factors.append(f"{mandatory_overdue_count} mandatory modules overdue")
            if no_activity_14_days:
                risk_factors.append("No activity for 14 days")
            if latest_failed_twice:
                risk_factors.append("Latest assessment failed twice")
        elif mandatory_overdue_count == 1 or score_below_pass:
            learner_risk = "Needs Attention"
            if mandatory_overdue_count == 1:
                risk_factors.append("1 mandatory module overdue")
            if score_below_pass:
                risk_factors.append("Assessment score below pass threshold")
        else:
            if assigned > 0:
                risk_factors.append("All modules progressing on schedule")
                risk_factors.append("Assessment scores above threshold")
            else:
                risk_factors.append("No modules assigned")
                
        user_evals[u.name] = {
            "assigned": assigned,
            "completed": completed,
            "failed": failed,
            "avg_progress": avg_progress,
            "risk": learner_risk,
            "risk_factors": risk_factors,
            "last_activity": last_activity_date,
            "next_deadline": next_deadline.strftime("%b %d, %Y") if next_deadline else "None"
        }
        
    return user_evals


@frappe.whitelist(allow_guest=True)
def get_learner_kpis():
    learner_roles = frappe.get_all("Has Role", filters={"role": "LMS-Learner"}, pluck="parent", ignore_permissions=True)
    filters = {"name": ("!=", "Administrator")}
    if learner_roles:
        filters["name"] = ("in", learner_roles)
        
    users = frappe.get_all("User", filters=filters, fields=["name", "enabled"], ignore_permissions=True)
    total = len(users)
    
    user_evals = _evaluate_user_risks(users)
    
    fourteen_days_ago = getdate(add_days(today(), -14))
    active = 0
    at_risk = 0
    
    for u in users:
        eval_data = user_evals.get(u.name, {})
        if eval_data.get("last_activity") and getdate(eval_data["last_activity"]) >= fourteen_days_ago:
            active += 1
        if eval_data.get("risk") in ["Overdue", "Needs Attention"]:
            at_risk += 1
            
    inactive = total - active
    
    return {
        "totalLearners": total,
        "activeLearners": active,
        "inactiveLearners": inactive,
        "atRiskLearners": at_risk
    }


@frappe.whitelist(allow_guest=True)
def get_learners(search="", limit=10, status="all", risk="all", offset=0):
    try:
        limit = int(limit)
        offset = int(offset)
    except Exception:
        limit = 10
        offset = 0

    filters = {"name": ("!=", "Administrator")}
    learner_roles = frappe.get_all("Has Role", filters={"role": "LMS-Learner"}, pluck="parent", ignore_permissions=True)
    if learner_roles:
        filters["name"] = ("in", learner_roles)
    if search:
        filters["full_name"] = ("like", f"%{search}%")
        
    order_by = "creation desc" if risk and risk.lower() == "recent" else "name asc"
    users = frappe.get_all("User", filters=filters, fields=["name", "email", "full_name", "enabled", "user_image"], order_by=order_by, ignore_permissions=True)

    user_evals = _evaluate_user_risks(users)
    
    results = []
    for u in users:
        eval_data = user_evals.get(u.name, {})
        learner_status = "Active" if u.enabled else "Inactive"
        
        avatar = u.user_image
        if not avatar:
            import urllib.parse
            encoded_name = urllib.parse.quote(u.full_name or u.name)
            avatar = f"https://ui-avatars.com/api/?name={encoded_name}&background=random&size=32"
        elif avatar.startswith("/"):
            avatar = get_url(avatar)

        results.append({
            "id": u.name,
            "name": u.full_name or u.name,
            "email": u.email,
            "avatar": f"url({avatar})",
            "department": "Engineering",
            "designation": "LMS Learner",
            "assignedCount": eval_data.get("assigned", 0),
            "completedCount": eval_data.get("completed", 0),
            "progress": int(eval_data.get("avg_progress", 0)),
            "status": learner_status,
            "risk": eval_data.get("risk", "On Track"),
            "risk_factors": eval_data.get("risk_factors", []),
            "next_deadline": eval_data.get("next_deadline", "None")
        })

    if status and status.lower() != "all":
        results = [r for r in results if r["status"].lower() == status.lower()]
        
    if risk and risk.lower() != "all" and risk.lower() != "recent":
        risk_map = {
            "at risk": ["overdue", "needs attention"],
            "overdue": ["overdue"],
            "needs attention": ["needs attention"],
            "on track": ["on track"]
        }
        filter_risk = risk.lower()
        if filter_risk in risk_map:
            results = [item for item in results if item["risk"].lower() in risk_map[filter_risk]]

    total = len(results)
    paginated = results[offset:offset+limit]

    return {
        "learners": paginated,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@frappe.whitelist(allow_guest=True)
def get_learner_details(user_id):
    user = frappe.get_doc("User", user_id)
    if not user:
        return {}

    eval_data = _evaluate_user_risks([user]).get(user.name, {})
    
    avatar = user.user_image
    if not avatar:
        import urllib.parse
        encoded_name = urllib.parse.quote(user.full_name or user.name)
        avatar = f"https://ui-avatars.com/api/?name={encoded_name}&background=random&size=32"
    elif avatar.startswith("/"):
        avatar = get_url(avatar)

    trackers = frappe.get_all("LMS Module Tracker", filters={"user": user.name}, fields=["name", "module", "status"])
    modules = frappe.get_all("LMS Module", fields=["name", "is_mandatory"])
    mod_dict = {m.name: m.is_mandatory for m in modules}

    mandatory_assigned = 0
    mandatory_completed = 0
    optional_assigned = 0
    optional_completed = 0

    for t in trackers:
        is_mand = mod_dict.get(t.module, 1)
        if is_mand:
            mandatory_assigned += 1
            if t.status == "Completed":
                mandatory_completed += 1
        else:
            optional_assigned += 1
            if t.status == "Completed":
                optional_completed += 1
                
    submissions = frappe.get_all("LMS Quiz Submission", filters={"user": user.name}, fields=["name", "quiz", "passed", "creation", "score"])
    
    total_assessments = len(set([s.quiz for s in submissions]))
    
    quiz_attempts = {}
    for s in submissions:
        quiz_attempts[s.quiz] = quiz_attempts.get(s.quiz, 0) + 1
        
    retakes = sum(1 for q, count in quiz_attempts.items() if count > 1)
    
    avg_score = 0
    highest_score = 0
    if submissions:
        valid_scores = [s.score for s in submissions]
        if valid_scores:
            avg_score = sum(valid_scores) / len(valid_scores)
            highest_score = max(valid_scores)
            
    chart_data = []
    
    quarters = {}
    for s in submissions:
        dt = getdate(s.creation)
        q = (dt.month - 1) // 3 + 1
        key = f"Q{q} {dt.year}"
        if key not in quarters:
            quarters[key] = []
        quarters[key].append(s.score)
            
    for k, v in quarters.items():
        chart_data.append({
            "label": k,
            "value": int(sum(v) / len(v)) if v else 0
        })
        
    chart_data.sort(key=lambda x: (x["label"].split()[1], x["label"].split()[0]))
    
    # If no chart data, mock it for UI demonstration
    if not chart_data:
        chart_data = [
            {"label": "Q1 2026", "value": 60},
            {"label": "Q2 2026", "value": 70},
            {"label": "Q3 2026", "value": 78},
            {"label": "Q4 2026", "value": 85},
        ]
        
    # If no trackers, mock the overview stats to match the mock assigned modules
    if not trackers:
        # User has no assignments, return empty details or zeros
        return {
            "profile": {
                "id": user.name,
                "name": user.full_name or user.name,
                "email": user.email,
                "avatar": avatar,
                "department": "Engineering",
                "designation": "LMS Learner",
                "joinedDate": user.creation.strftime("%b %d, %Y") if user.creation else "",
                "status": "Active" if user.enabled else "Inactive"
            },
            "overview": {
                "overallProgress": 0,
                "completedItems": 0,
                "totalItems": 0,
                "assessmentScore": 0,
                "highestScore": 0,
                "assessmentsTaken": 0,
                "retakes": 0,
                "learningPerformance": [],
                "modules": {
                    "total": 0,
                    "mandatoryCompleted": 0,
                    "mandatoryTotal": 0,
                    "optionalCompleted": 0,
                    "optionalTotal": 0
                },
                "learningPaths": {
                    "total": 0,
                    "mandatoryCompleted": 0,
                    "mandatoryTotal": 0,
                    "optionalCompleted": 0,
                    "optionalTotal": 0
                },
                "risk": "On Track",
                "riskFactors": ["No modules assigned"],
                "nextDeadline": "No upcoming deadlines"
            }
        }    
    return {
        "profile": {
            "id": user.name,
            "name": user.full_name or user.name,
            "email": user.email,
            "avatar": avatar,
            "department": "Engineering",
            "designation": "LMS Learner",
            "joinedDate": user.creation.strftime("%b %d, %Y") if user.creation else "",
            "status": "Active" if user.enabled else "Inactive"
        },
        "overview": {
            "overallProgress": int(eval_data.get("avg_progress", 0)),
            "completedItems": eval_data.get("completed", 0),
            "totalItems": eval_data.get("assigned", 0),
            "assessmentScore": int(avg_score),
            "highestScore": int(highest_score),
            "assessmentsTaken": total_assessments,
            "retakes": retakes,
            "learningPerformance": chart_data,
            "modules": {
                "total": mandatory_assigned + optional_assigned,
                "mandatoryCompleted": mandatory_completed,
                "mandatoryTotal": mandatory_assigned,
                "optionalCompleted": optional_completed,
                "optionalTotal": optional_assigned
            },
            "learningPaths": {
                "total": 0,
                "mandatoryCompleted": 0,
                "mandatoryTotal": 0,
                "optionalCompleted": 0,
                "optionalTotal": 0
            },
            "risk": eval_data.get("risk", "On Track"),
            "riskFactors": eval_data.get("risk_factors", []),
            "nextDeadline": eval_data.get("next_deadline", "None")
        }
    }

@frappe.whitelist(allow_guest=True)
def get_learner_assigned_modules(user_id, limit=10, offset=0):
    try:
        limit = int(limit)
        offset = int(offset)
    except:
        limit = 10
        offset = 0
        
    trackers = frappe.get_all(
        "LMS Module Tracker", 
        filters={"user": user_id}, 
        fields=["name", "module", "status", "progress_percentage", "started_on", "creation"],
        order_by="creation desc",
        ignore_permissions=True
    )
    
    modules = frappe.get_all("LMS Module", fields=["name", "module_name", "category", "duration", "is_mandatory"], ignore_permissions=True)
    mod_dict = {m.name: m for m in modules}
    
    results = []
    current_date = getdate(today())
    
    for t in trackers:
        mod = mod_dict.get(t.module)
        if not mod:
            continue
            
        due_date = "None"
        start = t.started_on or t.creation
        if start and mod.duration:
            due_dt = add_days(start, mod.duration)
            due_date_obj = getdate(due_dt)
            due_date = due_date_obj.strftime("%b %-d, %Y")
            
            # Check overdue
            if t.status != "Completed" and current_date > due_date_obj:
                t.status = "Overdue"
                
        results.append({
            "id": t.name,
            "moduleId": mod.name,
            "name": mod.module_name or mod.name,
            "category": mod.category or "General",
            "progress": int(t.progress_percentage or 0),
            "status": t.status or "Not Started",
            "dueDate": due_date,
            "isMandatory": bool(mod.is_mandatory)
        })
        
    total = len(results)
    paginated = results[offset:offset+limit]
    
    return {
        "items": paginated,
        "total": total,
        "limit": limit,
        "offset": offset
    }

@frappe.whitelist(allow_guest=True)
def seed_dummy_data():
    from frappe.utils import today, add_days
    user = "Administrator"
    
    # Check if we have the LMS Module doctype
    modules_data = [
        {"name": "Design Systems in Figma", "category": "Design", "mand": 1, "status": "Completed", "prog": 100, "start": -60},
        {"name": "Advanced React Patterns", "category": "Development", "mand": 1, "status": "Inprogress", "prog": 45, "start": -10},
        {"name": "Corporate Compliance 2026", "category": "Compliance", "mand": 1, "status": "Overdue", "prog": 0, "start": -90},
        {"name": "Communication Skills", "category": "Soft Skills", "mand": 0, "status": "Not Started", "prog": 0, "start": 0},
    ]
    
    for md in modules_data:
        mod_name = frappe.db.get_value("LMS Module", {"module_name": md["name"]}, "name")
        if not mod_name:
            doc = frappe.get_doc({
                "doctype": "LMS Module",
                "module_name": md["name"],
                "category": md["category"],
                "is_mandatory": md["mand"],
                "duration": 30
            })
            doc.insert(ignore_permissions=True)
            mod_name = doc.name
            
        if not frappe.db.exists("LMS Module Tracker", {"user": user, "module": mod_name}):
            tracker = frappe.get_doc({
                "doctype": "LMS Module Tracker",
                "user": user,
                "module": mod_name,
                "status": md["status"],
                "progress_percentage": md["prog"],
                "started_on": add_days(today(), md["start"]) if md["start"] < 0 else None
            })
            tracker.insert(ignore_permissions=True)
            
    subs = [
        {"q": "Q1", "date": "2026-02-15", "score": 60, "pass": 1},
        {"q": "Q2", "date": "2026-05-15", "score": 70, "pass": 1},
        {"q": "Q3", "date": "2026-08-15", "score": 78, "pass": 1},
        {"q": "Q4", "date": "2026-11-15", "score": 85, "pass": 1},
        {"q": "Q4", "date": "2026-11-10", "score": 40, "pass": 0},
    ]
    
    for s in subs:
        if not frappe.db.exists("LMS Quiz Submission", {"user": user, "creation": (">=", s["date"] + " 00:00:00"), "score": s["score"]}):
            sub = frappe.get_doc({
                "doctype": "LMS Quiz Submission",
                "user": user,
                "quiz": f"Quiz {s['q']}",
                "score": s["score"],
                "passed": s["pass"],
                "creation": s["date"] + " 12:00:00"
            })
            sub.flags.ignore_permissions = True
            sub.insert()
            frappe.db.set_value("LMS Quiz Submission", sub.name, "creation", s["date"] + " 12:00:00")
            
    frappe.db.commit()
    return "Seed complete!"
