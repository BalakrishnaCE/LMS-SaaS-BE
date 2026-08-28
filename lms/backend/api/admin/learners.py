import frappe
from frappe import _
from frappe.utils import get_url, add_days, today, getdate

def _evaluate_user_risks(users):
    if not users:
        return {}
        
    user_names = [u.name for u in users]

    # Fetch User Roles (for active/inactive check)
    roles = frappe.get_all("Has Role", filters={"parent": ("in", user_names), "role": "LMS-Learner"}, fields=["parent", "role"])
    user_has_learner_role = set(r.parent for r in roles)

    # Fetch User Settings (for designation)
    user_settings = frappe.get_all("LMS User Settings", filters={"system_user": ("in", user_names)}, fields=["system_user", "designation"])
    user_designation = {s.system_user: s.designation for s in user_settings}

    # Fetch User Teams
    team_members = frappe.get_all("LMS Team Member", filters={"user": ("in", user_names)}, fields=["user", "parent"])
    user_teams = {u: [] for u in user_names}
    for tm in team_members:
        user_teams[tm.user].append(tm.parent)

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
        
        total_progress = sum(float(t.progress_percentage or 0) for t in u_trackers)
        
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
            "next_deadline": next_deadline.strftime("%b %d, %Y") if next_deadline else "None",
            "department": user_teams[u.name][0] if user_teams.get(u.name) else "No Team",
            "designation": user_designation.get(u.name) or "",
            "has_trackers": len(u_trackers) > 0,
            "has_learner_role": u.name in user_has_learner_role
        }
        
    return user_evals


@frappe.whitelist(allow_guest=True)
def get_learner_kpis():
    learner_roles = frappe.get_all("Has Role", filters={"role": "LMS-Learner"}, pluck="parent", ignore_permissions=True)
    filters = {"name": ("!=", "Administrator")}
    if learner_roles:
        filters["name"] = ("in", [r for r in learner_roles if r != "Administrator"])
        
    users = frappe.get_all("User", filters=filters, fields=["name", "enabled"], ignore_permissions=True)
    total = len(users)
    
    user_evals = _evaluate_user_risks(users)
    
    fourteen_days_ago = getdate(add_days(today(), -14))
    active = 0
    at_risk = 0
    
    for u in users:
        eval_data = user_evals.get(u.name, {})
        has_lms_learner = eval_data.get("has_learner_role", False)
        has_trackers = eval_data.get("has_trackers", False)
        
        if has_lms_learner and has_trackers:
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
        filters["name"] = ("in", [r for r in learner_roles if r != "Administrator"])
    if search:
        filters["full_name"] = ("like", f"%{search}%")
        
    order_by = "creation desc" if risk and risk.lower() == "recent" else "name asc"
    users = frappe.get_all("User", filters=filters, fields=["name", "email", "full_name", "enabled", "user_image"], order_by=order_by, ignore_permissions=True)

    user_evals = _evaluate_user_risks(users)
    
    results = []
    for u in users:
        eval_data = user_evals.get(u.name, {})
        
        has_lms_learner = eval_data.get("has_learner_role", False)
        has_trackers = eval_data.get("has_trackers", False)
        learner_status = "Active" if (has_lms_learner and has_trackers) else "Inactive"
        
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
            "department": eval_data.get("department", "Engineering"),
            "designation": eval_data.get("designation", "LMS Learner"),
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

    trackers = frappe.get_all("LMS Module Tracker", filters={"user": user.name}, fields=["name", "module", "status", "creation"], order_by="creation asc")
    modules = frappe.get_all("LMS Module", fields=["name", "is_mandatory"])
    mod_dict = {m.name: m.is_mandatory for m in modules}

    # Get earliest tracker activity as "joined date"
    first_activity_date = trackers[0].creation if trackers else None

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
                
    lp_enrollments = frappe.get_all("LMS Learning Path Enrollment", filters={"learner": user.name}, fields=["name", "learning_path", "status"])
    learning_paths = frappe.get_all("LMS Learning Path", fields=["name", "is_mandatory"])
    lp_dict = {lp.name: lp.is_mandatory for lp in learning_paths}

    lp_mandatory_assigned = 0
    lp_mandatory_completed = 0
    lp_optional_assigned = 0
    lp_optional_completed = 0

    for lpe in lp_enrollments:
        is_mand = lp_dict.get(lpe.learning_path, 0)
        if is_mand:
            lp_mandatory_assigned += 1
            if lpe.status == "Completed":
                lp_mandatory_completed += 1
        else:
            lp_optional_assigned += 1
            if lpe.status == "Completed":
                lp_optional_completed += 1
                
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
            
    yearly_data = {}
    available_years = set()
    for s in submissions:
        dt = getdate(s.creation)
        available_years.add(dt.year)
        
    if not available_years:
        available_years.add(getdate(today()).year)
        
    available_years = sorted(list(available_years), reverse=True)
    
    # Initialize all years
    for y in available_years:
        yearly_data[str(y)] = {
            "chartData": [
                {"label": f"Q1 {y}", "value": 0},
                {"label": f"Q2 {y}", "value": 0},
                {"label": f"Q3 {y}", "value": 0},
                {"label": f"Q4 {y}", "value": 0}
            ],
            "avgScore": 0,
            "highestScore": 0,
            "assessmentsTaken": 0,
            "retakes": 0,
            "_scores": {1: [], 2: [], 3: [], 4: []},
            "_quizzes": {},
        }
        
    # Populate raw data
    for s in submissions:
        dt = getdate(s.creation)
        y = str(dt.year)
        q = (dt.month - 1) // 3 + 1
        
        yd = yearly_data[y]
        yd["_scores"][q].append(s.score)
        yd["_quizzes"][s.quiz] = yd["_quizzes"].get(s.quiz, 0) + 1
        
    # Finalize calculations
    for y, yd in yearly_data.items():
        all_scores = []
        for q in range(1, 5):
            scores = yd["_scores"][q]
            if scores:
                all_scores.extend(scores)
                yd["chartData"][q-1]["value"] = int(sum(scores) / len(scores))
                
        if all_scores:
            yd["avgScore"] = int(sum(all_scores) / len(all_scores))
            yd["highestScore"] = max(all_scores)
            
        yd["assessmentsTaken"] = len(yd["_quizzes"])
        yd["retakes"] = sum(1 for count in yd["_quizzes"].values() if count > 1)
        
        del yd["_scores"]
        del yd["_quizzes"]
        
    learning_performance = {
        "availableYears": available_years,
        "yearlyData": yearly_data
    }

    

    # If no trackers, mock the overview stats to match the mock assigned modules
    if not trackers:
        # User has no assignments, return empty details or zeros
        return {
            "profile": {
                "id": user.name,
                "name": user.full_name or user.name,
                "email": user.email,
                "avatar": avatar,
                "department": eval_data.get("department", "No Team"),
                "designation": eval_data.get("designation", "No Role"),
                "joinedDate": first_activity_date.strftime("%b %d, %Y") if first_activity_date else "",
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
                "learningPerformance": {
                    "availableYears": [getdate(today()).year],
                    "yearlyData": {
                        str(getdate(today()).year): {
                            "chartData": [
                                {"label": f"Q1 {getdate(today()).year}", "value": 0},
                                {"label": f"Q2 {getdate(today()).year}", "value": 0},
                                {"label": f"Q3 {getdate(today()).year}", "value": 0},
                                {"label": f"Q4 {getdate(today()).year}", "value": 0}
                            ],
                            "avgScore": 0,
                            "highestScore": 0,
                            "assessmentsTaken": 0,
                            "retakes": 0
                        }
                    }
                },
                "modules": {
                    "total": 0,
                    "mandatoryCompleted": 0,
                    "mandatoryTotal": 0,
                    "optionalCompleted": 0,
                    "optionalTotal": 0
                },
                "learningPaths": {
                    "total": lp_mandatory_assigned + lp_optional_assigned,
                    "mandatoryCompleted": lp_mandatory_completed,
                    "mandatoryTotal": lp_mandatory_assigned,
                    "optionalCompleted": lp_optional_completed,
                    "optionalTotal": lp_optional_assigned
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
            "department": eval_data.get("department", "No Team"),
            "designation": eval_data.get("designation", "No Role"),
            "joinedDate": first_activity_date.strftime("%b %d, %Y") if first_activity_date else "",
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
            "learningPerformance": learning_performance,
            "modules": {
                "total": mandatory_assigned + optional_assigned,
                "mandatoryCompleted": mandatory_completed,
                "mandatoryTotal": mandatory_assigned,
                "optionalCompleted": optional_completed,
                "optionalTotal": optional_assigned
            },
            "learningPaths": {
                "total": lp_mandatory_assigned + lp_optional_assigned,
                "mandatoryCompleted": lp_mandatory_completed,
                "mandatoryTotal": lp_mandatory_assigned,
                "optionalCompleted": lp_optional_completed,
                "optionalTotal": lp_optional_assigned
            },
            "risk": eval_data.get("risk", "On Track"),
            "riskFactors": eval_data.get("risk_factors", []),
            "nextDeadline": eval_data.get("next_deadline", "None")
        }
    }

@frappe.whitelist(allow_guest=True)
def get_learner_assigned_modules(user_id, limit=10, offset=0, categories=None, statuses=None, types=None, priorities=None):
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
    
    import json
    if categories and isinstance(categories, str):
        categories = json.loads(categories)
    if statuses and isinstance(statuses, str):
        statuses = json.loads(statuses)
    if types and isinstance(types, str):
        types = json.loads(types)
    if priorities and isinstance(priorities, str):
        priorities = json.loads(priorities)
    
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
                
        mod_status = t.status or "Not Started"
        mod_category = mod.category or "General"
        is_mandatory = bool(mod.is_mandatory)
        
        # Apply filters
        if categories and not any(c.lower() in mod_category.lower() for c in categories):
            continue
            
        if statuses and mod_status.lower() not in [s.lower() for s in statuses]:
            continue
            
        # Default mock type filtering (since we don't have distinct types in backend yet)
        mod_type = "Module"
        if types and mod_type.lower() not in [ty.lower() for ty in types]:
            continue
            
        mod_priority = "Mandatory" if is_mandatory else "Optional"
        if priorities and mod_priority.lower() not in [p.lower() for p in priorities]:
            continue
                
        results.append({
            "id": t.name,
            "moduleId": mod.name,
            "name": mod.module_name or mod.name,
            "category": mod_category,
            "progress": int(t.progress_percentage or 0),
            "status": mod_status,
            "dueDate": due_date,
            "isMandatory": is_mandatory
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
@frappe.whitelist(allow_guest=True)
def get_learner_assessments(user_id, categories=None, statuses=None, types=None, priorities=None):
    try:
        trackers = frappe.get_all("LMS Module Tracker", filters={"user": user_id}, fields=["name", "module", "status"])
        
        import json
        if categories and isinstance(categories, str): categories = json.loads(categories)
        if statuses and isinstance(statuses, str): statuses = json.loads(statuses)
        if types and isinstance(types, str): types = json.loads(types)
        if priorities and isinstance(priorities, str): priorities = json.loads(priorities)
        
        results = []
        
        for t in trackers:
            mod = frappe.get_doc("LMS Module", t.module)
            
            submissions = frappe.get_all("LMS Quiz Submission", filters={"enrollment": t.name}, fields=["quiz", "score", "passed"])
            
            ass_dict = {}
            for s in submissions:
                if s.quiz not in ass_dict:
                    ass_dict[s.quiz] = {"best_score": s.score, "attempts": 1, "passed": s.passed}
                else:
                    ass_dict[s.quiz]["attempts"] += 1
                    if s.score > ass_dict[s.quiz]["best_score"]:
                        ass_dict[s.quiz]["best_score"] = s.score
                    if s.passed:
                        ass_dict[s.quiz]["passed"] = 1
                        
            assessments_list = []
            for quiz_name, data in ass_dict.items():
                quiz = frappe.get_doc("LMS Quiz", quiz_name)
                # determine result badge
                res = "Passed" if data["passed"] else ("Failed" if data["attempts"] >= (quiz.max_attempts or 3) else "Needs attention")
                
                assessments_list.append({
                    "id": quiz_name,
                    "title": quiz.title,
                    "type": "Quiz",
                    "bestScore": data["best_score"],
                    "passScore": quiz.passing_percentage if quiz.is_passing_required else "--",
                    "attempts": f"{data['attempts']}/{quiz.max_attempts or 3}",
                    "result": res,
                    "lesson": "Lesson"
                })
                
            paths = frappe.get_all("LMS Learning Path Course", filters={"module": mod.name}, fields=["parent"])
            path_name = paths[0].parent if paths else None
            
            if path_name:
                path_item = next((r for r in results if r["title"] == path_name and r["type"] == "Learning Path"), None)
                if not path_item:
                    path_doc = frappe.get_doc("LMS Learning Path", path_name)
                    path_item = {
                        "id": path_name,
                        "title": path_name,
                        "type": "Learning Path",
                        "category": mod.category[0].category if mod.category else "Compliance",
                        "status": "Inprogress",
                        "modules": [],
                        "lessonsCount": 0,
                        "assessmentsCount": 0
                    }
                    results.append(path_item)
                
                mod_overall = sum([a["bestScore"] for a in assessments_list]) / len(assessments_list) if assessments_list else 0
                path_item["modules"].append({
                    "id": mod.name,
                    "title": mod.module_name,
                    "status": "Needs attention" if any(a["result"] == "Needs attention" for a in assessments_list) else t.status,
                    "assessments": assessments_list,
                    "lessonsCount": len(mod.lessons),
                    "assessmentsCount": len(assessments_list),
                    "overallScore": int(mod_overall)
                })
                path_item["lessonsCount"] += len(mod.lessons)
                path_item["assessmentsCount"] += len(assessments_list)
            else:
                mod_overall = sum([a["bestScore"] for a in assessments_list]) / len(assessments_list) if assessments_list else 0
                results.append({
                    "id": mod.name,
                    "title": mod.module_name,
                    "type": "Module",
                    "category": mod.category[0].category if mod.category else "Compliance",
                    "status": "Needs attention" if any(a["result"] == "Needs attention" for a in assessments_list) else t.status,
                    "lessonsCount": len(mod.lessons),
                    "assessmentsCount": len(assessments_list),
                    "assessments": assessments_list,
                    "overallScore": int(mod_overall)
                })
                
        # Apply filters
        if categories:
            results = [r for r in results if any(c.lower() in r["category"].lower() for c in categories)]
        if statuses:
            results = [r for r in results if r["status"].lower() in [s.lower() for s in statuses]]
        if types:
            results = [r for r in results if r["type"].lower() in [ty.lower() for ty in types]]
            
        total_assessments_taken = 0
        total_passed = 0
        score_sum = 0
        score_count = 0
        pending_tests = 0
        
        for r in results:
            mods = r.get("modules", []) if r["type"] == "Learning Path" else [r]
            
            # Determine path status based on modules
            if r["type"] == "Learning Path":
                if any(m["status"] == "Needs attention" for m in mods):
                    r["status"] = "Needs attention"
                elif any(m["status"] == "Failed" for m in mods):
                    r["status"] = "Failed"
                elif all(m["status"] == "Completed" for m in mods):
                    r["status"] = "Passed"
                else:
                    r["status"] = "Inprogress"
                    
            for m in mods:
                for a in m.get("assessments", []):
                    total_assessments_taken += 1
                    if a["result"] == "Passed":
                        total_passed += 1
                    elif a["result"] != "Passed":
                        pending_tests += 1
                    score_sum += a["bestScore"]
                    score_count += 1
                    
        stats = {
            "assessmentsTaken": total_assessments_taken,
            "averageScore": int(score_sum / score_count) if score_count > 0 else 0,
            "passingRate": total_passed,
            "pendingTests": pending_tests
        }
        
        return {
            "stats": stats,
            "cards": results
        }
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get Learner Assessments")
        return {"error": str(e)}

@frappe.whitelist(allow_guest=True)
def get_assessment_details(user_id, quiz_name):
    try:
        quiz = frappe.get_doc("LMS Quiz", quiz_name)
        
        submissions = frappe.get_all(
            "LMS Quiz Submission",
            filters={"user": user_id, "quiz": quiz_name},
            fields=["name", "score", "passed", "creation"],
            order_by="creation asc"
        )
        
        history = []
        for i, s in enumerate(submissions):
            attempt_num = i + 1
            history.insert(0, {
                "id": s.name,
                "attempt": f"Attempt {attempt_num}",
                "score": f"{int(s.score)}% {'Passed' if s.passed else 'Failed'}",
                "date": s.creation.strftime("%b %-d, %Y"),
                "duration": "14m 32s",
                "raw_score": s.score
            })
            
        total_attempts = len(submissions)
        best_score = max([s.score for s in submissions]) if submissions else 0
        latest_sub = submissions[-1] if submissions else None
        
        best_sub_name = None
        if submissions:
            best_sub = max(submissions, key=lambda x: x.score)
            best_sub_name = best_sub.name
            
        questions_performance = []
        correct_count = 0
        incorrect_count = 0
        
        if best_sub_name:
            responses = frappe.get_all(
                "LMS Quiz Response",
                filters={"parent": best_sub_name, "parenttype": "LMS Quiz Submission"},
                fields=["question", "is_correct"],
                order_by="idx asc"
            )
            
            import re
            for idx, r in enumerate(responses):
                q_doc = frappe.get_doc("LMS Quiz Question", r.question)
                is_correct = bool(r.is_correct)
                if is_correct:
                    correct_count += 1
                else:
                    incorrect_count += 1
                    
                q_text = re.sub('<[^<]+>', '', q_doc.question_text or '')
                
                questions_performance.append({
                    "id": r.question,
                    "index": idx + 1,
                    "text": q_text.strip(),
                    "isCorrect": is_correct
                })
                
        stats = {
            "questions": len(quiz.questions) if hasattr(quiz, "questions") else (correct_count + incorrect_count or 20),
            "correct": correct_count,
            "incorrect": incorrect_count,
            "attempts": total_attempts,
            "bestScore": f"{int(best_score)}%",
            "passingScore": f"{int(quiz.passing_percentage)}%" if getattr(quiz, "is_passing_required", 0) else "--",
            "timeTaken": "14m 32s",
            "dateTaken": latest_sub.creation.strftime("%b %-d, %Y") if latest_sub else "--"
        }
        
        return {
            "stats": stats,
            "history": history,
            "questions": questions_performance,
            "title": quiz.title
        }
        
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get Assessment Details API")
        return {"error": str(e)}



@frappe.whitelist(allow_guest=True)
def get_learning_filter_options():
    categories = frappe.get_all("LMS Course Category", pluck="name")
    return {
        "categories": categories,
        "statuses": [
            {"label": "Completed", "color": "#138B47", "bg": "#DDF3E7"},
            {"label": "Overdue", "color": "var(--status-overdue-fg)", "bg": "var(--status-overdue-bg)"},
            {"label": "Inprogress", "color": "var(--status-in-progress-fg)", "bg": "var(--status-in-progress-bg)"},
            {"label": "Not Started", "color": "#595F69", "bg": "#ECEDEF"},
            {"label": "Needs attention", "color": "#D97706", "bg": "#F5E9DB"},
            {"label": "Failed", "color": "#DC2626", "bg": "#FEE2E2"}
        ]
    }
