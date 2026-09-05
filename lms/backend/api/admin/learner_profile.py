import frappe
from frappe import _
from frappe.utils import get_url, add_days, today, getdate

def _evaluate_user_risks(users):
    if not users:
        return {}
        
    user_names = [u.name for u in users]

    # Fetch User Roles (for active/inactive check)
    roles = frappe.get_all("Has Role", filters={"parent": ("in", user_names), "role": ["in", ["LMS-Learner", "LMS-TL"]]}, fields=["parent", "role"])
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
    lp_trackers = frappe.get_all("LMS Learning Path Tracker", filters={"user": ("in", user_names)}, fields=["name", "user", "learning_path", "status", "progress_percentage", "started_on", "creation", "modified"])
    submissions = frappe.get_all("LMS Quiz Submission", filters={"user": ("in", user_names)}, fields=["name", "user", "quiz", "passed", "creation"], order_by="creation desc")
    
    user_trackers = {u: [] for u in user_names}
    for t in trackers:
        user_trackers[t.user].append(t)
        
    user_lp_trackers = {u: [] for u in user_names}
    for t in lp_trackers:
        user_lp_trackers[t.user].append(t)
        
    user_submissions = {u: [] for u in user_names}
    for s in submissions:
        user_submissions[s.user].append(s)

    current_date = getdate(today())
    fourteen_days_ago = add_days(today(), -14)
    
    user_evals = {}
    
    for u in users:
        u_trackers = user_trackers[u.name]
        u_lp_trackers = user_lp_trackers[u.name]
        u_submissions = user_submissions[u.name]
        
        assigned = len(u_trackers) + len(u_lp_trackers)
        completed = sum(1 for t in u_trackers if t.status == "Completed") + sum(1 for t in u_lp_trackers if t.status == "Completed")
        failed = sum(1 for t in u_trackers if t.status == "Failed") + sum(1 for t in u_lp_trackers if t.status == "Failed")
        
        total_progress = sum(float(t.progress_percentage or 0) for t in u_trackers) + sum(float(t.progress_percentage or 0) for t in u_lp_trackers)
        
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

        for t in u_lp_trackers:
            if not last_activity_date or getdate(t.modified) > getdate(last_activity_date):
                last_activity_date = t.modified
                        
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
            "department": ", ".join(user_teams[u.name]) if user_teams.get(u.name) else "No Team",
            "designation": user_designation.get(u.name) or "",
            "has_trackers": len(u_trackers) > 0,
            "has_learner_role": u.name in user_has_learner_role
        }
        
    return user_evals


@frappe.whitelist(allow_guest=True)
def get_learner_kpis():
    learner_roles = frappe.get_all("Has Role", filters={"role": ["in", ["LMS-Learner", "LMS-TL"]]}, pluck="parent", ignore_permissions=True)
    filters = {"name": ("!=", "Administrator")}
    if learner_roles:
        filters["name"] = ("in", [r for r in learner_roles if r != "Administrator"])
        
    users = frappe.get_all("User", filters=filters, fields=["name", "enabled"], ignore_permissions=True)
    total = len(users)
    
    user_evals = _evaluate_user_risks(users)
    
    fourteen_days_ago = getdate(add_days(today(), -14))
    thirty_days_ago = getdate(add_days(today(), -30))
    active = 0
    at_risk = 0
    
    for u in users:
        eval_data = user_evals.get(u.name, {})
        has_lms_learner = eval_data.get("has_learner_role", False)
        last_activity = eval_data.get("last_activity")
        
        if has_lms_learner and last_activity and getdate(last_activity) >= thirty_days_ago:
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
    learner_roles = frappe.get_all("Has Role", filters={"role": ["in", ["LMS-Learner", "LMS-TL"]]}, pluck="parent", ignore_permissions=True)
    if learner_roles:
        filters["name"] = ("in", [r for r in learner_roles if r != "Administrator"])
    if search:
        filters["full_name"] = ("like", f"%{search}%")
        
    order_by = "creation desc" if risk and risk.lower() == "recent" else "name asc"
    users = frappe.get_all("User", filters=filters, fields=["name", "email", "full_name", "enabled", "user_image"], order_by=order_by, ignore_permissions=True)

    user_evals = _evaluate_user_risks(users)
    
    thirty_days_ago = getdate(add_days(today(), -30))
    results = []
    for u in users:
        eval_data = user_evals.get(u.name, {})
        
        has_lms_learner = eval_data.get("has_learner_role", False)
        last_activity = eval_data.get("last_activity")
        
        learner_status = "Inactive"
        if has_lms_learner and last_activity and getdate(last_activity) >= thirty_days_ago:
            learner_status = "Active"
        
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
        # Check manual assignment
        is_mand = frappe.db.sql("""
            SELECT ma.is_mandatory
            FROM `tabLMS Module Assignment` ma
            INNER JOIN `tabLMS Assignment User` au ON au.parent = ma.name
            WHERE ma.module = %s AND au.user = %s
            ORDER BY ma.is_mandatory DESC LIMIT 1
        """, (t.module, user.name))
        
        # Check team assignment
        is_mand_team = frappe.db.sql("""
            SELECT ma.is_mandatory
            FROM `tabLMS Module Assignment` ma
            INNER JOIN `tabLMS Assignment Team` ta ON ta.parent = ma.name
            INNER JOIN `tabLMS Team Member` tm ON tm.parent = ta.team
            WHERE ma.module = %s AND tm.user = %s
            ORDER BY ma.is_mandatory DESC LIMIT 1
        """, (t.module, user.name))
        
        # Check everyone assignment
        is_mand_everyone = frappe.db.sql("""
            SELECT is_mandatory FROM `tabLMS Module Assignment`
            WHERE module = %s AND assignment_type = 'Everyone'
            ORDER BY is_mandatory DESC LIMIT 1
        """, (t.module,))
        
        is_mandatory = 0
        if is_mand and is_mand[0][0]:
            is_mandatory = 1
        elif is_mand_team and is_mand_team[0][0]:
            is_mandatory = 1
        elif is_mand_everyone and is_mand_everyone[0][0]:
            is_mandatory = 1
            
        if not is_mandatory:
            mod_doc_mand = frappe.db.get_value("LMS Module", t.module, "is_mandatory")
            if mod_doc_mand:
                is_mandatory = 1

        if is_mandatory:
            mandatory_assigned += 1
            if t.status == "Completed":
                mandatory_completed += 1
        else:
            optional_assigned += 1
            if t.status == "Completed":
                optional_completed += 1
                
    lp_trackers = frappe.get_all("LMS Learning Path Tracker", filters={"user": user.name}, fields=["name", "learning_path", "status"])

    lp_mandatory_assigned = 0
    lp_mandatory_completed = 0
    lp_optional_assigned = 0
    lp_optional_completed = 0

    for lpe in lp_trackers:
        # Check if mandatory via Learning Path Assignment (Manual)
        is_mand = frappe.db.sql("""
            SELECT ma.is_mandatory
            FROM `tabLMS Learning Path Assignment` ma
            INNER JOIN `tabLMS LP Assignment User` au ON au.parent = ma.name
            WHERE ma.learning_path = %s AND au.user = %s
            ORDER BY ma.is_mandatory DESC LIMIT 1
        """, (lpe.learning_path, user.name))
        
        # Check if mandatory via Learning Path Assignment (Team)
        is_mand_team = frappe.db.sql("""
            SELECT ma.is_mandatory
            FROM `tabLMS Learning Path Assignment` ma
            INNER JOIN `tabLMS Assignment Team` ta ON ta.parent = ma.name
            INNER JOIN `tabLMS Team Member` tm ON tm.parent = ta.team
            WHERE ma.learning_path = %s AND tm.user = %s
            ORDER BY ma.is_mandatory DESC LIMIT 1
        """, (lpe.learning_path, user.name))
        
        is_mandatory = 0
        if is_mand and is_mand[0][0]:
            is_mandatory = 1
        elif is_mand_team and is_mand_team[0][0]:
            is_mandatory = 1
            
        if not is_mandatory:
            # Fallback to LP document if no explicit assignment found (e.g. self-enrolled)
            lp_doc_mand = frappe.db.get_value("LMS Learning Path", lpe.learning_path, "is_mandatory")
            if lp_doc_mand:
                is_mandatory = 1

        if is_mandatory:
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

    

    has_lms_learner = eval_data.get("has_learner_role", False)
    has_trackers = eval_data.get("has_trackers", False)
    learner_status = "Active" if (has_lms_learner and has_trackers) else "Inactive"

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
                "status": learner_status
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
            "status": learner_status
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

