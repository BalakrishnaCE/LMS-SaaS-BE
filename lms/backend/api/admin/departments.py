import frappe
from frappe.utils import add_days, today, getdate

@frappe.whitelist(allow_guest=False)
def get_departments_data():
    """
    Returns data for the Departments admin dashboard.
    """
    teams = frappe.get_all("LMS Team", fields=["name", "team_name", "is_active"])
    
    total_departments = len([t for t in teams if t.get("is_active", 0) == 1])
    
    all_team_members = frappe.get_all("LMS Team Member", fields=["user", "parent"])
    
    admin_users = set(frappe.get_all("Has Role", filters={"role": "LMS-Admin"}, pluck="parent"))
    current_learners = [r for r in frappe.get_all("Has Role", filters={
        "role": ["in", ["LMS-Learner", "LMS-Manager", "LMS-TL"]],
        "parent": ["not in", ["Administrator", "Guest"]]
    }, pluck="parent") if r not in admin_users]
    
    unique_learners = set(current_learners)
    total_learners = len(unique_learners)
    
    thirty_days_ago = add_days(today(), -30)
    all_trackers = frappe.get_all("LMS Module Tracker", fields=["user", "status", "modified"])
    active_learners_set = set()
    for t in all_trackers:
        if t.user not in unique_learners:
            continue
        if t.status and t.status in ("In Progress", "Completed", "Failed"):
            if t.modified and getdate(t.modified) >= getdate(thirty_days_ago):
                active_learners_set.add(t.user)
    active_learners = len(active_learners_set)
        
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
                status = "Overdue" if learning_completion < 50 else "On Track"

        is_active = bool(team.get("is_active", 0) == 1)
        if not is_active:
            status = "Inactive"
                
        departments_list.append({
            "id": team.name,
            "department_name": team.team_name,
            "learners_count": learners_count,
            "managers": managers,
            "learning_completion": learning_completion,
            "incomplete": incomplete,
            "status": status,
            "is_active": 1 if is_active else 0
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
    """Returns users who can be assigned as department managers (LMS-TL role)"""
    users = frappe.db.sql("""
        SELECT 
            u.name, 
            u.full_name, 
            u.user_image,
            s.designation,
            (
                SELECT GROUP_CONCAT(DISTINCT t.team_name SEPARATOR ', ') 
                FROM `tabLMS Team` t
                WHERE EXISTS (SELECT 1 FROM `tabLMS Team Member` m WHERE m.parent = t.name AND m.user = u.name)
                   OR EXISTS (SELECT 1 FROM `tabLMS Team Lead` l WHERE l.parent = t.name AND l.user = u.name)
            ) as department
        FROM `tabUser` u
        JOIN `tabHas Role` r ON r.parent = u.name
        LEFT JOIN `tabLMS User Settings` s ON s.system_user = u.name
        WHERE u.enabled = 1 AND u.name != 'Administrator' AND u.user_type = 'System User' AND r.role = 'LMS-TL'
    """, as_dict=True)
    
    # Also fetch their current department assignments if needed, 
    # but for now we just return the users list.
    managers = []
    for u in users:
        managers.append({
            "id": u.name,
            "name": u.full_name or u.name,
            "avatar": u.user_image,
            "role": u.designation or "System User",
            "department": u.department or ""
        })
    return managers

@frappe.whitelist(allow_guest=False)
def get_available_learners():
    """Returns users who can be assigned as learners (LMS-Learner or LMS-TL)"""
    users = frappe.db.sql("""
        SELECT DISTINCT 
            u.name, 
            u.full_name, 
            u.user_image,
            s.designation,
            (
                SELECT GROUP_CONCAT(DISTINCT t.team_name SEPARATOR ', ') 
                FROM `tabLMS Team` t
                WHERE EXISTS (SELECT 1 FROM `tabLMS Team Member` m WHERE m.parent = t.name AND m.user = u.name)
                   OR EXISTS (SELECT 1 FROM `tabLMS Team Lead` l WHERE l.parent = t.name AND l.user = u.name)
            ) as department
        FROM `tabUser` u
        JOIN `tabHas Role` r ON r.parent = u.name
        LEFT JOIN `tabLMS User Settings` s ON s.system_user = u.name
        WHERE u.enabled = 1 AND u.name != 'Administrator' AND u.user_type = 'System User' AND r.role IN ('LMS-Learner', 'LMS-TL')
    """, as_dict=True)
    
    learners = []
    for u in users:
        learners.append({
            "id": u.name,
            "name": u.full_name or u.name,
            "avatar": u.user_image,
            "role": u.designation or "System User",
            "department": u.department or ""
        })
    return learners

@frappe.whitelist(allow_guest=False)
def create_department(team_name, managers=None, learners=None, assignment_mode='keep', department_id=None, assignment_groups=None):
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
        
    if isinstance(assignment_groups, str):
        assignment_groups = json.loads(assignment_groups)
        
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
        if assignment_mode == 'remove':
            # Remove these learners from any existing teams
            teams_with_learners = frappe.db.sql("""
                SELECT DISTINCT parent FROM `tabLMS Team Member` 
                WHERE user IN %s AND parent != %s
            """, (tuple(learners), team.name or ""), as_dict=True)
            
            for t in teams_with_learners:
                existing_team = frappe.get_doc("LMS Team", t.parent)
                updated_learners = [m for m in existing_team.get("learners", []) if m.user not in learners]
                if len(updated_learners) != len(existing_team.get("learners", [])):
                    existing_team.set("learners", updated_learners)
                    existing_team.save(ignore_permissions=True)

        for learner_id in learners:
            team.append("learners", {
                "user": learner_id
            })
            
    if department_id:
        team.save(ignore_permissions=True)
    else:
        team.insert(ignore_permissions=True)
        
    # Process assignment groups
    if assignment_groups:
        for group in assignment_groups:
            valid_emails = group.get("learners", [])
            selected_content = group.get("content", [])
            
            if not valid_emails or not selected_content:
                continue
                
            modules = [c for c in selected_content if c.get("type") == "module"]
            learning_paths = [c for c in selected_content if c.get("type") == "learning_path"]

            # Module Assignments
            for module_item in modules:
                module_id = module_item.get("id")
                if not module_id: continue
                
                existing = frappe.db.get_value("LMS Module Assignment", 
                    {"module": module_id, "assignment_type": "Manual"}, "name")
                
                if existing:
                    doc = frappe.get_doc("LMS Module Assignment", existing)
                    existing_emails = {row.user for row in doc.get("learners", [])}
                    newly_added = []
                    for email in valid_emails:
                        if email not in existing_emails:
                            doc.append("learners", {"user": email})
                            newly_added.append(email)
                    doc.flags.ignore_version = True
                    doc.save(ignore_permissions=True)
                    # Restore any Unassigned tracker for re-added learners
                    for email in newly_added:
                        tracker = frappe.db.get_value("LMS Module Tracker", 
                            {"user": email, "module": module_id}, 
                            ["name", "status", "progress_percentage"], as_dict=True)
                        if tracker and tracker.status == "Unassigned":
                            restored = "In Progress" if (tracker.progress_percentage or 0) > 0 else "Not started"
                            frappe.db.set_value("LMS Module Tracker", tracker.name, "status", restored)
                else:
                    doc = frappe.new_doc("LMS Module Assignment")
                    doc.module = module_id
                    doc.assignment_type = "Manual"
                    for email in valid_emails:
                        doc.append("learners", {"user": email})
                    doc.insert(ignore_permissions=True)
                    for email in valid_emails:
                        tracker = frappe.db.get_value("LMS Module Tracker", 
                            {"user": email, "module": module_id}, 
                            ["name", "status", "progress_percentage"], as_dict=True)
                        if tracker and tracker.status == "Unassigned":
                            restored = "In Progress" if (tracker.progress_percentage or 0) > 0 else "Not started"
                            frappe.db.set_value("LMS Module Tracker", tracker.name, "status", restored)

            # Learning Path Assignments
            for lp_item in learning_paths:
                lp_id = lp_item.get("id")
                if not lp_id: continue
                
                existing = frappe.db.get_value("LMS Learning Path Assignment", 
                    {"learning_path": lp_id, "assignment_type": "Manual"}, "name")
                    
                if existing:
                    doc = frappe.get_doc("LMS Learning Path Assignment", existing)
                    existing_emails = {row.user for row in doc.get("learners", [])}
                    for email in valid_emails:
                        if email not in existing_emails:
                            doc.append("learners", {"user": email})
                    doc.flags.ignore_version = True
                    doc.save(ignore_permissions=True)
                else:
                    doc = frappe.new_doc("LMS Learning Path Assignment")
                    doc.learning_path = lp_id
                    doc.assignment_type = "Manual"
                    for email in valid_emails:
                        doc.append("learners", {"user": email})
                    doc.insert(ignore_permissions=True)
    
    return {"status": "success", "department_id": team.name}

@frappe.whitelist(allow_guest=False)
def get_department_details(department_id):
    """
    Returns granular data for a specific department (LMS Team) for the details dashboard.
    """
    if not department_id:
        frappe.throw("Department ID is required")
        
    team = frappe.get_doc("LMS Team", department_id)
    
    # Get managers (team leads)
    manager_ids = [m.user for m in team.get("team_leads", []) if m.user]
    if not manager_ids and getattr(team, "team_lead", None):
        manager_ids = [team.team_lead]

    manager_details = []
    if manager_ids:
        mgr_users = frappe.db.get_all(
            "User",
            filters={"name": ("in", manager_ids)},
            fields=["name", "full_name", "user_image", "email"]
        )
        mgr_map = {u.name: u for u in mgr_users}
        for m_id in manager_ids:
            u_info = mgr_map.get(m_id)
            manager_details.append({
                "id": m_id,
                "name": (u_info.full_name if u_info and u_info.full_name else m_id),
                "email": (u_info.email if u_info and u_info.email else m_id),
                "user_image": u_info.user_image if u_info else None
            })

    primary_evaluator_id = manager_details[0]["id"] if manager_details else None
    primary_evaluator_name = manager_details[0]["name"] if manager_details else None

    # Get learners
    learner_ids = [m.user for m in team.get("learners", []) if m.user]
    
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
    
    learnings_list = []
    
    if learner_ids:
        learner_set = set(learner_ids)
        
        # ── 1. Module Assignments & Trackers ──────────────────────────
        assigned_module_learners = {}  # module_id -> set(user_ids)
        module_assignment_info = {}    # module_id -> {"is_mandatory": bool, "duration": int}
        
        # Everyone assignments (applies to all learners in this department)
        everyone_mod_assigns = frappe.db.sql("""
            SELECT ma.module, ma.duration, ma.is_mandatory
            FROM `tabLMS Module Assignment` ma
            JOIN `tabLMS Module` m ON ma.module = m.name
            WHERE ma.assignment_type = 'Everyone'
        """, as_dict=True)
        for ea in everyone_mod_assigns:
            m_id = ea.module
            if m_id not in assigned_module_learners:
                assigned_module_learners[m_id] = set()
            assigned_module_learners[m_id].update(learner_set)
            if m_id not in module_assignment_info:
                module_assignment_info[m_id] = {"is_mandatory": bool(ea.is_mandatory), "duration": ea.duration or 0}
            elif ea.is_mandatory:
                module_assignment_info[m_id]["is_mandatory"] = True

        # Team assignments for this department
        team_mod_assigns = frappe.db.sql("""
            SELECT ma.module, ma.duration, ma.is_mandatory
            FROM `tabLMS Module Assignment` ma
            JOIN `tabLMS Assignment Team` at ON at.parent = ma.name
            JOIN `tabLMS Module` m ON ma.module = m.name
            WHERE ma.assignment_type = 'Team' AND at.team IN %s
        """, ((department_id, team.name),), as_dict=True)
        for ta in team_mod_assigns:
            m_id = ta.module
            if m_id not in assigned_module_learners:
                assigned_module_learners[m_id] = set()
            assigned_module_learners[m_id].update(learner_set)
            if m_id not in module_assignment_info:
                module_assignment_info[m_id] = {"is_mandatory": bool(ta.is_mandatory), "duration": ta.duration or 0}
            elif ta.is_mandatory:
                module_assignment_info[m_id]["is_mandatory"] = True

        # Manual assignments for specific learners in this department
        manual_mod_assigns = frappe.db.sql("""
            SELECT ma.module, au.user, ma.duration, ma.is_mandatory
            FROM `tabLMS Module Assignment` ma
            JOIN `tabLMS Assignment User` au ON au.parent = ma.name
            JOIN `tabLMS Module` m ON ma.module = m.name
            WHERE ma.assignment_type = 'Manual' AND au.user IN %s
        """, (tuple(learner_ids),), as_dict=True)
        for ma in manual_mod_assigns:
            m_id = ma.module
            if m_id not in assigned_module_learners:
                assigned_module_learners[m_id] = set()
            assigned_module_learners[m_id].add(ma.user)
            if m_id not in module_assignment_info:
                module_assignment_info[m_id] = {"is_mandatory": bool(ma.is_mandatory), "duration": ma.duration or 0}
            elif ma.is_mandatory:
                module_assignment_info[m_id]["is_mandatory"] = True

        # Module trackers for learners in this department
        module_trackers = frappe.db.sql("""
            SELECT t.module, t.user, t.status, m.module_name, m.duration, m.is_mandatory
            FROM `tabLMS Module Tracker` t
            JOIN `tabLMS Module` m ON t.module = m.name
            WHERE t.user IN %s AND t.status != 'Unassigned'
        """, (tuple(learner_ids),), as_dict=True)
        
        module_user_status = {}
        for mt in module_trackers:
            m_id = mt.module
            if m_id not in assigned_module_learners:
                assigned_module_learners[m_id] = set()
            assigned_module_learners[m_id].add(mt.user)
            module_user_status[(m_id, mt.user)] = (mt.status or "").strip().lower()
            if m_id not in module_assignment_info:
                module_assignment_info[m_id] = {"is_mandatory": bool(mt.is_mandatory), "duration": mt.duration or 0}
            elif mt.is_mandatory:
                module_assignment_info[m_id]["is_mandatory"] = True

        # Process each assigned module
        module_dict = {}
        for m_id, assigned_users in assigned_module_learners.items():
            if not assigned_users:
                continue
            
            m_doc = frappe.db.get_value("LMS Module", m_id, ["module_name", "duration", "is_mandatory"], as_dict=True)
            if not m_doc:
                continue
            
            categories = frappe.get_all("LMS Module Category", filters={"parent": m_id}, fields=["category"])
            cat_names = " • ".join([c.category for c in categories]) if categories else "General"
            lesson_count = frappe.db.count("LMS Module Lesson Child", {"parent": m_id})
            
            info = module_assignment_info.get(m_id, {})
            is_mandatory = info.get("is_mandatory", False) or bool(m_doc.is_mandatory)
            duration = info.get("duration") or m_doc.duration or 0
            duration_str = f"{duration} {'day' if duration == 1 else 'days'}" if duration else "--"
            
            completed_cnt = 0
            not_started_cnt = 0
            in_prog_cnt = 0
            
            for u in assigned_users:
                st = module_user_status.get((m_id, u))
                if st == "completed":
                    completed_cnt += 1
                elif st in ["not started", "not_started"]:
                    not_started_cnt += 1
                elif st:
                    in_prog_cnt += 1
                else:
                    # User is assigned but has not started yet (no tracker row)
                    not_started_cnt += 1
                    
            assigned_cnt = len(assigned_users)
            
            if is_mandatory:
                mandatory_modules_total += assigned_cnt
                mandatory_modules_completed += completed_cnt
            else:
                optional_modules_total += assigned_cnt
                optional_modules_completed += completed_cnt
                
            module_dict[m_id] = {
                "id": m_id,
                "name": m_doc.module_name or m_id,
                "type": "Module",
                "category": cat_names,
                "lessons": lesson_count,
                "duration": duration,
                "duration_formatted": duration_str,
                "is_mandatory": is_mandatory,
                "isMandatory": is_mandatory,
                "priority": "High" if is_mandatory else "Medium",
                "assigned": assigned_cnt,
                "completed": completed_cnt,
                "not_started": not_started_cnt,
                "in_progress": in_prog_cnt,
                "due_date": duration_str
            }

        # ── 2. Learning Path Assignments & Trackers ───────────────────
        assigned_path_learners = {}  # path_id -> set(user_ids)
        path_assignment_info = {}    # path_id -> {"is_mandatory": bool, "duration": int}
        
        everyone_lp_assigns = frappe.db.sql("""
            SELECT lpa.learning_path, lpa.duration, lpa.is_mandatory
            FROM `tabLMS Learning Path Assignment` lpa
            JOIN `tabLMS Learning Path` p ON lpa.learning_path = p.name
            WHERE lpa.assignment_type = 'Everyone'
        """, as_dict=True)
        for ea in everyone_lp_assigns:
            p_id = ea.learning_path
            if p_id not in assigned_path_learners:
                assigned_path_learners[p_id] = set()
            assigned_path_learners[p_id].update(learner_set)
            if p_id not in path_assignment_info:
                path_assignment_info[p_id] = {"is_mandatory": bool(ea.is_mandatory), "duration": ea.duration or 0}
            elif ea.is_mandatory:
                path_assignment_info[p_id]["is_mandatory"] = True

        team_lp_assigns = frappe.db.sql("""
            SELECT lpa.learning_path, lpa.duration, lpa.is_mandatory
            FROM `tabLMS Learning Path Assignment` lpa
            JOIN `tabLMS Assignment Team` at ON at.parent = lpa.name
            JOIN `tabLMS Learning Path` p ON lpa.learning_path = p.name
            WHERE lpa.assignment_type = 'Team' AND at.team IN %s
        """, ((department_id, team.name),), as_dict=True)
        for ta in team_lp_assigns:
            p_id = ta.learning_path
            if p_id not in assigned_path_learners:
                assigned_path_learners[p_id] = set()
            assigned_path_learners[p_id].update(learner_set)
            if p_id not in path_assignment_info:
                path_assignment_info[p_id] = {"is_mandatory": bool(ta.is_mandatory), "duration": ta.duration or 0}
            elif ta.is_mandatory:
                path_assignment_info[p_id]["is_mandatory"] = True

        manual_lp_assigns = frappe.db.sql("""
            SELECT lpa.learning_path, au.user, lpa.duration, lpa.is_mandatory
            FROM `tabLMS Learning Path Assignment` lpa
            JOIN `tabLMS LP Assignment User` au ON au.parent = lpa.name
            JOIN `tabLMS Learning Path` p ON lpa.learning_path = p.name
            WHERE lpa.assignment_type = 'Manual' AND au.user IN %s
        """, (tuple(learner_ids),), as_dict=True)
        for ma in manual_lp_assigns:
            p_id = ma.learning_path
            if p_id not in assigned_path_learners:
                assigned_path_learners[p_id] = set()
            assigned_path_learners[p_id].add(ma.user)
            if p_id not in path_assignment_info:
                path_assignment_info[p_id] = {"is_mandatory": bool(ma.is_mandatory), "duration": ma.duration or 0}
            elif ma.is_mandatory:
                path_assignment_info[p_id]["is_mandatory"] = True

        path_trackers = frappe.db.sql("""
            SELECT t.learning_path, t.user, t.status, p.path_name, p.duration, p.is_mandatory
            FROM `tabLMS Learning Path Tracker` t
            JOIN `tabLMS Learning Path` p ON t.learning_path = p.name
            WHERE t.user IN %s AND t.status != 'Unassigned'
        """, (tuple(learner_ids),), as_dict=True)
        
        path_user_status = {}
        for pt in path_trackers:
            p_id = pt.learning_path
            if p_id not in assigned_path_learners:
                assigned_path_learners[p_id] = set()
            assigned_path_learners[p_id].add(pt.user)
            path_user_status[(p_id, pt.user)] = (pt.status or "").strip().lower()
            if p_id not in path_assignment_info:
                path_assignment_info[p_id] = {"is_mandatory": bool(pt.is_mandatory), "duration": pt.duration or 0}
            elif pt.is_mandatory:
                path_assignment_info[p_id]["is_mandatory"] = True

        path_dict = {}
        for p_id, assigned_users in assigned_path_learners.items():
            if not assigned_users:
                continue
                
            p_doc = frappe.db.get_value("LMS Learning Path", p_id, ["path_name", "duration", "is_mandatory"], as_dict=True)
            if not p_doc:
                continue
                
            module_count = frappe.db.count("LMS Learning Path Course", {"parent": p_id})
            info = path_assignment_info.get(p_id, {})
            is_mandatory = info.get("is_mandatory", False) or bool(p_doc.is_mandatory)
            duration = info.get("duration") or p_doc.duration or 0
            duration_str = f"{duration} {'day' if duration == 1 else 'days'}" if duration else "--"
            
            completed_cnt = 0
            not_started_cnt = 0
            in_prog_cnt = 0
            
            for u in assigned_users:
                st = path_user_status.get((p_id, u))
                if st == "completed":
                    completed_cnt += 1
                elif st in ["not started", "not_started"]:
                    not_started_cnt += 1
                elif st:
                    in_prog_cnt += 1
                else:
                    not_started_cnt += 1
                    
            assigned_cnt = len(assigned_users)
            
            if is_mandatory:
                mandatory_paths_total += assigned_cnt
                mandatory_paths_completed += completed_cnt
            else:
                optional_paths_total += assigned_cnt
                optional_paths_completed += completed_cnt
                
            path_dict[p_id] = {
                "id": p_id,
                "name": p_doc.path_name or p_id,
                "type": "Learning path",
                "category": "Curriculum",
                "lessons": module_count,
                "duration": duration,
                "duration_formatted": duration_str,
                "is_mandatory": is_mandatory,
                "isMandatory": is_mandatory,
                "priority": "High" if is_mandatory else "Medium",
                "assigned": assigned_cnt,
                "completed": completed_cnt,
                "not_started": not_started_cnt,
                "in_progress": in_prog_cnt,
                "due_date": duration_str
            }

        # ── 3. Combine & Assign Status ────────────────────────────────
        for k, v in module_dict.items():
            if v["completed"] == v["assigned"] and v["assigned"] > 0:
                v["status"] = "Completed"
            elif v["not_started"] == v["assigned"]:
                v["status"] = "Not Started"
            elif v["in_progress"] > 0 or v["completed"] > 0:
                v["status"] = "Inprogress"
            else:
                v["status"] = "Not Started"
            learnings_list.append(v)
            
        for k, v in path_dict.items():
            if v["completed"] == v["assigned"] and v["assigned"] > 0:
                v["status"] = "Completed"
            elif v["not_started"] == v["assigned"]:
                v["status"] = "Not Started"
            elif v["in_progress"] > 0 or v["completed"] > 0:
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
                   q.quiz_type, q.max_attempts, q.evaluation_method, q.owner as quiz_owner,
                   s.user, s.score, s.passed, s.submitted_on,
                   t.module as module_id, m.module_name, m.duration as module_duration,
                   t.started_on
            FROM `tabLMS Quiz Submission` s
            JOIN `tabLMS Quiz` q ON s.quiz = q.name
            LEFT JOIN `tabLMS Module Tracker` t ON s.enrollment = t.name
            LEFT JOIN `tabLMS Module` m ON t.module = m.name
            WHERE s.user IN %s
            ORDER BY s.submitted_on ASC
        """, (tuple(learner_ids),), as_dict=True)

        # Fallback: resolve module from module final_assessments when enrollment is missing
        missing_quiz_ids = list({r.id for r in submission_data if not r.module_id})
        quiz_module_map = {}
        if missing_quiz_ids:
            for r in frappe.db.sql("""
                SELECT ma.assessment as quiz, m.name as module_id, m.module_name, m.duration
                FROM `tabLMS Module Assessment` ma
                JOIN `tabLMS Module` m ON ma.parent = m.name
                WHERE ma.parenttype = 'LMS Module' AND ma.assessment IN %s
            """, (tuple(missing_quiz_ids),), as_dict=True):
                quiz_module_map.setdefault(r.quiz, r)

        # Learning paths assigned to this department's learners or team (module -> path)
        module_lp_map = {}
        lp_rows = frappe.db.sql("""
            SELECT DISTINCT lp.name as learning_path, lp.path_name, lp.duration, c.module
            FROM `tabLMS Learning Path` lp
            JOIN `tabLMS Learning Path Course` c ON c.parent = lp.name
            LEFT JOIN `tabLMS Learning Path Assignment` lpa ON lpa.learning_path = lp.name
            LEFT JOIN `tabLMS LP Assignment User` au ON au.parent = lpa.name
            LEFT JOIN `tabLMS Assignment Team` at ON at.parent = lpa.name
            LEFT JOIN `tabLMS Learning Path Tracker` lpt ON lpt.learning_path = lp.name AND lpt.user IN %(learners)s AND lpt.status != 'Unassigned'
            WHERE (
                au.user IN %(learners)s
                OR at.team = %(dept)s
                OR lpa.assignment_type = 'Everyone'
                OR lpt.name IS NOT NULL
            )
        """, {"learners": tuple(learner_ids), "dept": department_id}, as_dict=True)
        for r in lp_rows:
            module_lp_map.setdefault(r.module, r)

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
                module_id = row.module_id
                module_name = row.module_name
                module_duration = row.module_duration
                if not module_id and row.id in quiz_module_map:
                    fm = quiz_module_map[row.id]
                    module_id, module_name, module_duration = fm.module_id, fm.module_name, fm.duration

                lp = module_lp_map.get(module_id) if module_id else None
                if lp:
                    source_name, source_type = lp.path_name, "Learning Path"
                    duration = lp.duration or module_duration
                else:
                    source_name = module_name or (module_id if module_id else "--")
                    source_type = "Module" if (module_name or module_id) else ""
                    duration = module_duration

                quiz_type = (row.quiz_type or "Quiz").strip()
                is_qa = "QA" in quiz_type or quiz_type == "QA Assessment"
                assessment_type = "QA Assessment" if is_qa else "Quiz Assessment"

                quiz_dict[row.id] = {
                    "id": row.id,
                    "name": row.name or assessment_type,
                    "context": "Assessment",
                    "assessment_type": assessment_type,
                    "is_qa": is_qa,
                    "source": source_name,
                    "source_type": source_type,
                    "module_id": module_id,
                    "duration": duration or 0,
                    "max_attempts": row.max_attempts or 0,
                    "required_score": row.required_score or 0,
                    "quiz_owner": row.get("quiz_owner"),
                    "user_best_score": {},
                    "completed_users": set(),
                    "failed_users": set(),
                    "attempt_users": set(),
                    "attempt_count": 0,
                    "earliest_start": None,
                    "failed_count": 0,
                    "to_evaluate_count": 0,
                }

            quiz = quiz_dict[row.id]
            quiz["attempt_count"] += 1
            quiz["attempt_users"].add(row.user)

            start = row.started_on or row.submitted_on
            if start and (quiz["earliest_start"] is None or start < quiz["earliest_start"]):
                quiz["earliest_start"] = start

            if row.score is not None:
                if row.user not in quiz["user_best_score"] or row.score > quiz["user_best_score"][row.user]:
                    quiz["user_best_score"][row.user] = row.score
            else:
                quiz["to_evaluate_count"] += 1

            if row.passed:
                quiz["completed_users"].add(row.user)
                quiz["failed_users"].discard(row.user)
            elif row.score is not None and not row.passed:
                quiz["failed_count"] += 1
                if row.user not in quiz["completed_users"]:
                    quiz["failed_users"].add(row.user)

        all_failed_users = set()
        for v in quiz_dict.values():
            all_failed_users.update(v["failed_users"])

        failed_user_profiles = {}
        if all_failed_users:
            u_rows = frappe.db.get_all(
                "User",
                filters={"name": ("in", list(all_failed_users))},
                fields=["name", "full_name", "user_image", "email"]
            )
            for u in u_rows:
                failed_user_profiles[u.name] = {
                    "id": u.name,
                    "name": u.full_name or u.name,
                    "avatar": u.user_image,
                    "email": u.email or u.name
                }

        for k, v in quiz_dict.items():
            enrolled_learners = None
            if v.get("module_id") and v["module_id"] in assigned_module_learners:
                enrolled_learners = assigned_module_learners[v["module_id"]]
            elif v.get("source_type") == "Learning Path":
                for p_id, p_learners in assigned_path_learners.items():
                    if p_id == v["source"] or p_learners:
                        enrolled_learners = p_learners
                        break
            if not enrolled_learners:
                enrolled_learners = v["attempt_users"]

            assigned_count = len(enrolled_learners) if enrolled_learners else len(v["attempt_users"])
            completed_count = len(v["completed_users"])
            failed_learners = len(v["failed_users"])
            attempted_count = len(v["attempt_users"])
            yet_to_complete = max(0, assigned_count - completed_count)

            failed_learners_list = []
            for u_id in v["failed_users"]:
                profile = failed_user_profiles.get(u_id, {
                    "id": u_id,
                    "name": u_id,
                    "avatar": None,
                    "email": u_id
                })
                u_score = v["user_best_score"].get(u_id)
                failed_learners_list.append({
                    "id": profile["id"],
                    "name": profile["name"],
                    "avatar": profile["avatar"],
                    "email": profile["email"],
                    "score": u_score
                })

            user_scores = [sc for sc in v["user_best_score"].values() if sc is not None]
            avg_score = int(round(sum(user_scores) / len(user_scores))) if user_scores else None
            pass_rate = int(round((completed_count / attempted_count) * 100)) if attempted_count > 0 else (100 if completed_count > 0 else None)

            if v["to_evaluate_count"] > 0:
                status = "Awaiting evaluation"
            elif failed_learners > 0:
                status = "Has Failures"
            elif completed_count > 0 and yet_to_complete == 0:
                status = "All Passed"
            elif completed_count > 0 or attempted_count > 0:
                status = "In Progress"
            else:
                status = "In Progress"

            due_date = None
            if v["duration"] and v["earliest_start"]:
                due_date = frappe.utils.add_days(frappe.utils.getdate(v["earliest_start"]), int(v["duration"]))

            duration = v.get("duration") or 0
            duration_formatted = f"{duration} {'day' if duration == 1 else 'days'}" if duration else "--"

            eval_id = primary_evaluator_id or v.get("quiz_owner")
            eval_name = primary_evaluator_name
            if not eval_name and eval_id:
                eval_name = frappe.db.get_value("User", eval_id, "full_name") or eval_id

            v["yet_to_complete"] = yet_to_complete
            assessments_list.append({
                "id": v["id"],
                "name": v["name"],
                "context": v["context"],
                "assessment_type": v["assessment_type"],
                "source": v["source"],
                "source_type": v["source_type"],
                "score": avg_score,
                "avg_score": avg_score,
                "completion_score": avg_score or 0,
                "required_score": v["required_score"],
                "due_date": str(due_date) if due_date else None,
                "duration": duration,
                "duration_formatted": duration_formatted,
                "completed": completed_count,
                "failed": failed_learners,
                "failed_learners": failed_learners_list,
                "assigned_count": assigned_count,
                "attempted_count": attempted_count,
                "pass_rate": pass_rate,
                "yet_to_complete": yet_to_complete,
                "to_evaluate": v["to_evaluate_count"],
                "evaluator_id": eval_id or "",
                "evaluator_name": eval_name or "Department Manager",
                "status": status
            })

        assessments_completed_count = sum(a["completed"] for a in assessments_list)
        all_eval_scores = [a["score"] for a in assessments_list if a["score"] is not None]
        average_assessment_score = int(round(sum(all_eval_scores) / len(all_eval_scores))) if all_eval_scores else 0
        total_attempts = sum(a["attempted_count"] for a in assessments_list)
        if total_attempts > 0:
            assessment_completion = int(round((assessments_completed_count / total_attempts) * 100))
        elif assessments_list:
            passed_assessments = len([a for a in assessments_list if a["status"] in ["Completed", "Evaluated", "Passed", "All Passed"]])
            assessment_completion = int(round((passed_assessments / len(assessments_list)) * 100))
        else:
            assessment_completion = 0
        pending_assessments_count = sum(a["yet_to_complete"] for a in assessments_list)
            
    # Learners Table Data
    learners_list = []
    needs_attention = 0
    
    if learner_ids:
        users_data = frappe.db.get_all("User", 
            filters={"name": ("in", learner_ids)}, 
            fields=["name", "full_name", "user_image", "last_login", "enabled"]
        )
        
        from lms.backend.api.admin.learner_profile import _evaluate_user_risks
        user_evals = _evaluate_user_risks(users_data)
        
        for u in users_data:
            eval_data = user_evals.get(u.name, {})
            assigned_count = eval_data.get("assigned", 0)
            completed_count = eval_data.get("completed", 0)
            progress = int(round(eval_data.get("avg_progress", 0)))
            risk = eval_data.get("risk", "On Track")
            risk_factors = eval_data.get("risk_factors", [])
            next_deadline = eval_data.get("next_deadline", "None")
            
            # Status Logic
            has_lms_learner = eval_data.get("has_learner_role", False)
            is_active = (has_lms_learner and eval_data.get("has_in_progress", False)) or bool(u.enabled and u.last_login and getdate(u.last_login) >= getdate(thirty_days_ago))
            account_status = "Active" if is_active else "Inactive"
            
            if risk in ["Needs Attention", "Overdue"]:
                needs_attention += 1
                
            learners_list.append({
                "id": u.name,
                "name": u.full_name or u.name,
                "email": u.name,
                "avatar": u.user_image,
                "designation": eval_data.get("designation") or u.get("designation") or "Learner",
                "assigned_learning": f"{assigned_count} assigned · {completed_count} completed",
                "assignedCount": assigned_count,
                "completedCount": completed_count,
                "account_status": account_status,
                "status": account_status,
                "progress": progress,
                "progress_status": risk,
                "risk": risk,
                "risk_factors": risk_factors,
                "next_deadline": next_deadline
            })
            
    return {
        "department": {
            "id": team.name,
            "name": team.team_name,
            "description": "Department learning and performance",
            "manager_id": primary_evaluator_id,
            "manager_name": primary_evaluator_name
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
        "managers": manager_details,
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

@frappe.whitelist(allow_guest=False)
def get_department_names():
    return frappe.get_all("LMS Team", filters={"is_active": 1}, fields=["name", "team_name"])

@frappe.whitelist(allow_guest=False)
def activate_department(department_id):
    try:
        team_name = department_id
        if not frappe.db.exists("LMS Team", team_name):
            matched = frappe.db.get_value("LMS Team", {"team_name": department_id}, "name")
            if matched:
                team_name = matched
            else:
                frappe.throw(f"Department '{department_id}' not found")

        frappe.db.set_value("LMS Team", team_name, "is_active", 1)
        frappe.db.commit()
        return {"status": "success", "message": "Department activated successfully"}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Activate Department")
        return {"status": "error", "message": str(e)}

@frappe.whitelist(allow_guest=False)
def deactivate_department(department_id):
    try:
        team_name = department_id
        if not frappe.db.exists("LMS Team", team_name):
            matched = frappe.db.get_value("LMS Team", {"team_name": department_id}, "name")
            if matched:
                team_name = matched
            else:
                frappe.throw(f"Department '{department_id}' not found")

        frappe.db.set_value("LMS Team", team_name, "is_active", 0)
        frappe.db.commit()
        return {"status": "success", "message": "Department deactivated successfully"}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Deactivate Department")
        return {"status": "error", "message": str(e)}

@frappe.whitelist()
def delete_department(department_id):
    try:
        if not frappe.db.exists("LMS Team", department_id):
            frappe.throw("Department not found")

        # 1. Remove from assignments
        assign_teams = frappe.get_all("LMS Assignment Team", filters={"team": department_id}, fields=["name", "parent"])
        for at in assign_teams:
            frappe.delete_doc("LMS Assignment Team", at.name, ignore_permissions=True, force=1)

        # 2. Delete LMS Team
        frappe.delete_doc("LMS Team", department_id, ignore_permissions=True, force=1)
        return {"status": "success", "message": "Department deleted successfully"}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Delete Department")
        return {"status": "error", "message": str(e)}



