import frappe
from frappe.utils import add_days, today, getdate

@frappe.whitelist(allow_guest=False)
def get_departments_data():
    """
    Returns data for the Departments admin dashboard.
    """
    teams = frappe.get_all("LMS Team", filters={"is_active": 1}, fields=["name", "team_name"])
    
    total_departments = len(teams)
    
    all_team_members = frappe.get_all("LMS Team Member", fields=["user", "parent"])
    unique_learners = set([m.user for m in all_team_members])
    total_learners = len(unique_learners)
    
    # Active learners (logged in last 30 days)
    thirty_days_ago = add_days(today(), -30)
    
    active_learners = 0
    if unique_learners:
        active_learners = frappe.db.count("User", {
            "name": ("in", list(unique_learners)),
            "last_login": (">=", thirty_days_ago)
        })
        
    # Average completion
    # Average of progress_percentage across all LMS Module Trackers for these users
    avg_completion = 0
    if unique_learners:
        # Instead of calculating average manually, we can query it
        avg = frappe.db.sql("""
            SELECT AVG(progress_percentage) 
            FROM `tabLMS Module Tracker` 
            WHERE user IN %s
        """, (tuple(unique_learners),))[0][0]
        avg_completion = int(avg) if avg else 0

    departments_list = []
    
    for team in teams:
        # Learners count
        learners_in_team = [m.user for m in all_team_members if m.parent == team.name]
        learners_count = len(learners_in_team)
        
        # Managers
        leads = frappe.get_all("LMS Team Lead", filters={"parent": team.name}, fields=["user"])
        managers = []
        for lead in leads:
            user_data = frappe.db.get_value("User", lead.user, ["full_name", "user_image"], as_dict=True)
            if user_data:
                managers.append({
                    "name": user_data.full_name,
                    "avatar": user_data.user_image
                })
        
        learning_completion = 0
        incomplete = 0
        status = "On Track"
        
        if learners_in_team:
            # Average progress for this team
            team_avg = frappe.db.sql("""
                SELECT AVG(progress_percentage) 
                FROM `tabLMS Module Tracker` 
                WHERE user IN %s
            """, (tuple(learners_in_team),))[0][0]
            learning_completion = int(team_avg) if team_avg else 0
            
            # Incomplete trackers
            incomplete = frappe.db.count("LMS Module Tracker", {
                "user": ("in", learners_in_team),
                "status": ("!=", "Completed")
            })
            
            # Simplified status check
            if incomplete > 0:
                # If they have incomplete, they might be overdue, but we will simplify 
                # as calculating true overdue requires joining assignments. 
                # For demo purposes and speed, if avg is very low, mark overdue.
                # Actually, let's just do a basic logic for now or mark "On Track"
                status = "Overdue" if learning_completion < 50 else "On Track"
                
        departments_list.append({
            "id": team.name,
            "department_name": team.team_name,
            "learners_count": learners_count,
            "managers": managers,
            "learning_completion": learning_completion,
            "incomplete": incomplete,
            "status": status
        })
        
    return {
        "stats": {
            "total_departments": total_departments,
            "total_learners": total_learners,
            "active_learners": active_learners,
            "avg_completion": avg_completion
        },
        "departments": departments_list
    }

@frappe.whitelist(allow_guest=False)
def get_available_managers():
    """Returns users who can be assigned as department managers"""
    users = frappe.get_all("User", filters={"enabled": 1, "user_type": "System User"}, fields=["name", "full_name", "user_image"])
    
    # Also fetch their current department assignments if needed, 
    # but for now we just return the users list.
    managers = []
    for u in users:
        managers.append({
            "id": u.name,
            "name": u.full_name or u.name,
            "avatar": u.user_image,
            "role": "System User"
        })
    return managers

@frappe.whitelist(allow_guest=False)
def create_department(team_name, managers=None, learners=None, department_id=None):
    """
    Creates a new LMS Team or updates an existing one and assigns managers and learners.
    managers: List of user IDs
    learners: List of user IDs
    """
    import json
    
    if not team_name:
        frappe.throw("Department Name is required")
        
    if isinstance(managers, str):
        managers = json.loads(managers)
        
    if isinstance(learners, str):
        learners = json.loads(learners)
        
    team = None
    if department_id:
        if not frappe.db.exists("LMS Team", department_id):
            frappe.throw(f"Department {department_id} not found")
        team = frappe.get_doc("LMS Team", department_id)
        team.team_name = team_name
    else:
        # Check if team already exists by name
        if frappe.db.exists("LMS Team", {"team_name": team_name}):
            frappe.throw(f"Department with name '{team_name}' already exists.")
            
        team = frappe.get_doc({
            "doctype": "LMS Team",
            "team_name": team_name,
            "is_active": 1
        })
    
    # Clear existing to replace with new state
    team.set("team_leads", [])
    team.set("learners", [])
    
    # Add managers
    if managers:
        for manager_id in managers:
            team.append("team_leads", {
                "user": manager_id
            })
            
    # Add learners
    if learners:
        for learner_id in learners:
            team.append("learners", {
                "user": learner_id
            })
            
    if department_id:
        team.save(ignore_permissions=True)
    else:
        team.insert(ignore_permissions=True)
    
    return {"status": "success", "department_id": team.name}

@frappe.whitelist(allow_guest=False)
def get_department_details(department_id):
    """
    Returns granular data for a specific department (LMS Team) for the details dashboard.
    """
    if not department_id:
        frappe.throw("Department ID is required")
        
    team = frappe.get_doc("LMS Team", department_id)
    
    # Get learners
    learner_ids = [m.user for m in team.get("learners", [])]
    
    total_learners = len(learner_ids)
    
    # Active learners (logged in last 30 days)
    thirty_days_ago = add_days(today(), -30)
    active_learners = 0
    if learner_ids:
        active_learners = frappe.db.count("User", {
            "name": ("in", learner_ids),
            "last_login": (">=", thirty_days_ago)
        })
        
    # Learning completion
    learning_completion = 0
    if learner_ids:
        trackers = frappe.get_all("LMS Module Tracker", filters={"user": ("in", learner_ids), "status": ("!=", "Unassigned")}, fields=["progress_percentage"])
        if trackers:
            total_prog = sum([(t.progress_percentage or 0) for t in trackers])
            learning_completion = int(total_prog / len(trackers))
        
    # Assessment & Quizzes
    assessment_completion = 0
    average_assessment_score = 0
    assessments_completed_count = 0
    total_assignments_count = 0
    descriptive_assessments_count = 0
    
    if learner_ids:
        total_assignments_count = frappe.db.count("LMS Module Tracker", {"user": ("in", learner_ids), "status": ("!=", "Unassigned")})
        
        # Average quiz score
        submissions = frappe.get_all("LMS Quiz Submission", filters={"user": ("in", learner_ids)}, fields=["user", "score", "passed"])
        assessments_completed_count = len(submissions)
        
        if submissions:
            total_score = sum([(s.score or 0) for s in submissions])
            average_assessment_score = int(total_score / len(submissions))
            
            # Calculate completion based on unique users who submitted quizzes
            unique_submitters = len(set([s.user for s in submissions]))
            assessment_completion = int((unique_submitters / len(learner_ids)) * 100) if len(learner_ids) > 0 else 0
            
            descriptive_assessments_count = len([s for s in submissions if not s.score and not s.passed])
        
    # Achievements
    achievements_earned = 0
    achievements_list = []
    if learner_ids:
        achievements_earned = frappe.db.count("LMS Learner Badge", {"user": ("in", learner_ids)})
        
        badges = frappe.get_all("LMS Badge", fields=["name as badge_name", "badge_image", "description"])
        
        badge_counts = frappe.db.sql("""
            SELECT badge, user
            FROM `tabLMS Learner Badge`
            WHERE user IN %s
        """, (tuple(learner_ids),), as_dict=True)
        
        # Group users by badge
        badge_users_map = {}
        for b in badge_counts:
            if b.badge not in badge_users_map:
                badge_users_map[b.badge] = []
            badge_users_map[b.badge].append(b.user)
        
        for b in badges:
            earned_by_users = badge_users_map.get(b.badge_name, [])
            achievements_list.append({
                "badge_name": b.badge_name,
                "badge_image": b.badge_image,
                "description": b.description,
                "earned_count": len(earned_by_users),
                "earned_by": earned_by_users
            })
            
        achievements_list.sort(key=lambda x: x["earned_count"], reverse=True)
        
    # Learning Progress Breakdowns
    mandatory_modules_completed = 0
    mandatory_modules_total = 0
    optional_modules_completed = 0
    optional_modules_total = 0
    
    mandatory_paths_completed = 0
    mandatory_paths_total = 0
    optional_paths_completed = 0
    optional_paths_total = 0
    
    if learner_ids:
        module_trackers = frappe.db.sql("""
            SELECT t.status, m.is_mandatory 
            FROM `tabLMS Module Tracker` t
            JOIN `tabLMS Module` m ON t.module = m.name
            WHERE t.user IN %s AND t.status != 'Unassigned'
        """, (tuple(learner_ids),), as_dict=True)
        
        for mt in module_trackers:
            if mt.is_mandatory:
                mandatory_modules_total += 1
                if mt.status == "Completed":
                    mandatory_modules_completed += 1
            else:
                optional_modules_total += 1
                if mt.status == "Completed":
                    optional_modules_completed += 1
                    
        path_trackers = frappe.db.sql("""
            SELECT t.status, p.is_mandatory
            FROM `tabLMS Learning Path Tracker` t
            JOIN `tabLMS Learning Path` p ON t.learning_path = p.name
            WHERE t.user IN %s AND t.status != 'Unassigned'
        """, (tuple(learner_ids),), as_dict=True)
        
        for pt in path_trackers:
            if pt.is_mandatory:
                mandatory_paths_total += 1
                if pt.status == "Completed":
                    mandatory_paths_completed += 1
            else:
                optional_paths_total += 1
                if pt.status == "Completed":
                    optional_paths_completed += 1
                    
    # ==========================================
    # NEW: Learnings Tab Data
    # ==========================================
    learnings_list = []
    if learner_ids:
        # Modules
        module_data = frappe.db.sql("""
            SELECT t.module as id, m.module_name as name, t.status, m.duration
            FROM `tabLMS Module Tracker` t
            JOIN `tabLMS Module` m ON t.module = m.name
            WHERE t.user IN %s AND t.status != 'Unassigned'
        """, (tuple(learner_ids),), as_dict=True)
        
        module_dict = {}
        for row in module_data:
            if row.id not in module_dict:
                # get categories
                categories = frappe.get_all("LMS Module Category", filters={"parent": row.id}, fields=["category"])
                cat_names = " • ".join([c.category for c in categories]) if categories else "General"
                
                # get lesson count
                lesson_count = frappe.db.count("LMS Module Lesson Child", {"parent": row.id})
                
                module_dict[row.id] = {
                    "id": row.id,
                    "name": row.name,
                    "type": "Module",
                    "category": cat_names,
                    "lessons": lesson_count,
                    "duration": row.duration or 0,
                    "assigned": 0,
                    "completed": 0,
                    "not_started": 0,
                    "in_progress": 0,
                    "due_date": "No Due Date"
                }
            
            module_dict[row.id]["assigned"] += 1
            if row.status == "Completed":
                module_dict[row.id]["completed"] += 1
            elif row.status == "Not Started":
                module_dict[row.id]["not_started"] += 1
            else:
                module_dict[row.id]["in_progress"] += 1
                
        # Learning Paths
        path_data = frappe.db.sql("""
            SELECT t.learning_path as id, p.path_name as name, t.status
            FROM `tabLMS Learning Path Tracker` t
            JOIN `tabLMS Learning Path` p ON t.learning_path = p.name
            WHERE t.user IN %s AND t.status != 'Unassigned'
        """, (tuple(learner_ids),), as_dict=True)
        
        path_dict = {}
        for row in path_data:
            if row.id not in path_dict:
                # get modules count
                module_count = frappe.db.count("LMS Learning Path Course", {"parent": row.id})
                
                path_dict[row.id] = {
                    "id": row.id,
                    "name": row.name,
                    "type": "Learning path",
                    "category": "Curriculum",
                    "lessons": module_count,
                    "duration": 0,
                    "assigned": 0,
                    "completed": 0,
                    "not_started": 0,
                    "in_progress": 0,
                    "due_date": "No Due Date"
                }
                
            path_dict[row.id]["assigned"] += 1
            if row.status == "Completed":
                path_dict[row.id]["completed"] += 1
            elif row.status == "Not Started":
                path_dict[row.id]["not_started"] += 1
            else:
                path_dict[row.id]["in_progress"] += 1
                
        # Combine
        for k, v in module_dict.items():
            if v["completed"] == v["assigned"] and v["assigned"] > 0:
                v["status"] = "Completed"
            elif v["not_started"] == v["assigned"]:
                v["status"] = "Not Started"
            elif v["in_progress"] > 0 or v["not_started"] > 0:
                v["status"] = "Inprogress"
            else:
                v["status"] = "Not Started"
            learnings_list.append(v)
            
        for k, v in path_dict.items():
            if v["completed"] == v["assigned"] and v["assigned"] > 0:
                v["status"] = "Completed"
            elif v["not_started"] == v["assigned"]:
                v["status"] = "Not Started"
            elif v["in_progress"] > 0 or v["not_started"] > 0:
                v["status"] = "Inprogress"
            else:
                v["status"] = "Not Started"
            learnings_list.append(v)
            
    # ==========================================
    # NEW: Assessment Tab Data
    # ==========================================
    assessments_list = []
    pending_assessments_count = 0
    learners_retested_count = 0
    
    if learner_ids:
        submission_data = frappe.db.sql("""
            SELECT s.quiz as id, q.title as name, q.passing_percentage as required_score, 
                   s.user, s.score, s.passed
            FROM `tabLMS Quiz Submission` s
            JOIN `tabLMS Quiz` q ON s.quiz = q.name
            WHERE s.user IN %s
        """, (tuple(learner_ids),), as_dict=True)
        
        # Calculate retests
        user_quiz_counts = {}
        for row in submission_data:
            key = (row.user, row.id)
            user_quiz_counts[key] = user_quiz_counts.get(key, 0) + 1
        
        retested_users = set([u for (u, q), count in user_quiz_counts.items() if count > 1])
        learners_retested_count = len(retested_users)
        
        quiz_dict = {}
        for row in submission_data:
            if row.id not in quiz_dict:
                quiz_dict[row.id] = {
                    "id": row.id,
                    "name": row.name,
                    "context": "Assessment",
                    "required_score": row.required_score or 0,
                    "total_score_sum": 0,
                    "score_count": 0,
                    "completed_users": set(),
                    "failed_count": 0,
                    "to_evaluate_count": 0,
                }
                
            quiz = quiz_dict[row.id]
            
            if row.score is not None:
                quiz["total_score_sum"] += row.score
                quiz["score_count"] += 1
            else:
                quiz["to_evaluate_count"] += 1
                
            if row.passed:
                quiz["completed_users"].add(row.user)
            elif row.score is not None and not row.passed:
                quiz["failed_count"] += 1
                
        for k, v in quiz_dict.items():
            completed_count = len(v["completed_users"])
            yet_to_complete = max(0, total_learners - completed_count)
            avg_score = int(v["total_score_sum"] / v["score_count"]) if v["score_count"] > 0 else 0
            
            if completed_count == total_learners and total_learners > 0:
                status = "Passed"
            elif v["failed_count"] > 0:
                status = "Failed"
            else:
                status = "Inprogress"
                
            pending_assessments_count += v["to_evaluate_count"]
            
            assessments_list.append({
                "id": v["id"],
                "name": v["name"],
                "context": v["context"],
                "completion_score": avg_score,
                "required_score": v["required_score"],
                "completed": completed_count,
                "yet_to_complete": yet_to_complete,
                "failed": v["failed_count"],
                "to_evaluate": v["to_evaluate_count"],
                "status": status
            })
            
    # Learners Table Data
    learners_list = []
    needs_attention = 0
    
    if learner_ids:
        users_data = frappe.db.get_all("User", 
            filters={"name": ("in", learner_ids)}, 
            fields=["name", "full_name", "user_image", "last_login", "enabled"]
        )
        
        for u in users_data:
            # Get their trackers
            user_trackers = frappe.get_all("LMS Module Tracker", 
                filters={"user": u.name, "status": ("!=", "Unassigned")},
                fields=["status", "progress_percentage"]
            )
            
            assigned_count = len(user_trackers)
            completed_count = len([t for t in user_trackers if t.status == "Completed"])
            
            # Progress bar
            progress = 0
            if assigned_count > 0:
                progress = sum([t.progress_percentage or 0 for t in user_trackers]) / assigned_count
                
            # Status Logic
            is_active = bool(u.enabled) and (u.last_login and u.last_login >= getdate(thirty_days_ago))
            account_status = "Active" if is_active else "Inactive"
            
            progress_status = "On Track"
            if progress < 30 and assigned_count > 0:
                progress_status = "Overdue"
            elif progress < 60 and assigned_count > 0:
                progress_status = "Needs Attention"
                
            if progress_status == "Needs Attention" or progress_status == "Overdue":
                needs_attention += 1
                
            learners_list.append({
                "id": u.name,
                "name": u.full_name or u.name,
                "avatar": u.user_image,
                "designation": u.get("designation") or "Learner",
                "assigned_learning": f"{assigned_count} assigned - {completed_count} completed",
                "account_status": account_status,
                "progress": int(progress),
                "progress_status": progress_status
            })
            
    return {
        "department": {
            "id": team.name,
            "name": team.team_name,
            "description": "Department learning and performance"
        },
        "stats": {
            "total_learners": total_learners,
            "active_learners": active_learners,
            "learning_completion": learning_completion,
            "assessment_completion": assessment_completion,
            "average_assessment_score": average_assessment_score,
            "assessments_completed_count": assessments_completed_count,
            "total_assignments_count": total_assignments_count,
            "descriptive_assessments_count": descriptive_assessments_count,
            "achievements_earned": achievements_earned,
            "needs_attention": int((needs_attention / total_learners * 100)) if total_learners > 0 else 0,
            "pending_assessments": pending_assessments_count,
            "learners_retested": learners_retested_count,
            "learning_progress": {
                "total_learnings": mandatory_modules_total + optional_modules_total + mandatory_paths_total + optional_paths_total,
                "modules": {
                    "total": mandatory_modules_total + optional_modules_total,
                    "mandatory_completed": mandatory_modules_completed,
                    "mandatory_total": mandatory_modules_total,
                    "optional_completed": optional_modules_completed,
                    "optional_total": optional_modules_total
                },
                "paths": {
                    "total": mandatory_paths_total + optional_paths_total,
                    "mandatory_completed": mandatory_paths_completed,
                    "mandatory_total": mandatory_paths_total,
                    "optional_completed": optional_paths_completed,
                    "optional_total": optional_paths_total
                }
            }
        },
        "learners": learners_list,
        "learnings": learnings_list,
        "assessments": assessments_list,
        "achievements": achievements_list
    }

@frappe.whitelist()
def unassign_department_learning(department_id, item_id, item_type):
    try:
        team = frappe.get_doc("LMS Team", department_id)
        learner_ids = [m.user for m in team.get("learners", [])]
        
        from lms.backend.api.admin.learner_assessments import unassign_learning
        
        for user_id in learner_ids:
            unassign_learning(user_id, item_id, item_type)
            
        return {"status": "success", "unassigned_count": len(learner_ids)}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Unassign Department Learning")
        return {"status": "error", "message": str(e)}

@frappe.whitelist()
def remove_learner_from_department(department_id, learner_id):
    try:
        team = frappe.get_doc("LMS Team", department_id)
        
        # Remove learner from the learners child table
        updated_learners = [m for m in team.get("learners", []) if m.user != learner_id]
        team.set("learners", updated_learners)
        
        team.save(ignore_permissions=True)
        return {"status": "success"}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Remove Learner from Department")
        return {"status": "error", "message": str(e)}
