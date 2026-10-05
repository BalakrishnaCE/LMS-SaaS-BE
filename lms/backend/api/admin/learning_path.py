import frappe
from frappe import _

@frappe.whitelist()
def get_learning_paths():
    """
    Returns aggregated statistics and a list of all Learning Paths.
    """
    paths = frappe.get_all(
        "LMS Learning Path",
        fields=["name", "path_name", "status", "description", "image", "is_sequential", "modified", "is_mandatory"],
        order_by="modified desc"
    )

    # Get modules for each path
    for path in paths:
        courses = frappe.get_all(
            "LMS Learning Path Course",
            filters={"parent": path.name},
            fields=["module", "sequence_order"],
            order_by="sequence_order asc"
        )
        path["modules"] = courses
        path["module_count"] = len(courses)
        
        # Get category
        categories = frappe.get_all(
            "LMS Module Category",
            filters={"parent": path.name, "parenttype": "LMS Learning Path"},
            fields=["category"]
        )
        if categories:
            path["category"] = categories[0].category
        else:
            path["category"] = ""
        
        # Calculate completion rate
        enrollments = frappe.get_all(
            "LMS Learning Path Enrollment",
            filters={"learning_path": path.name},
            fields=["status", "completion_percentage"]
        )
        completed = sum(1 for e in enrollments if e.status == "Completed")
        path["enrollment_count"] = len(enrollments)
        path["completed_count"] = completed

    # Calculate Header Stats
    total_paths = len(paths)
    draft_paths = sum(1 for p in paths if p.status == "Draft")
    
    overdue_learners = 0 
    review_required = 0

    return {
        "stats": {
            "total_paths": total_paths,
            "overdue_learners": overdue_learners,
            "draft_paths": draft_paths,
            "review_required": review_required
        },
        "paths": paths
    }

@frappe.whitelist()
def get_learning_path_detail(path_id, version=None):
    """
    Returns the full detail of a single Learning Path for the details view.
    Includes metadata, categories, and all assigned modules with their details.
    """
    path = frappe.get_doc("LMS Learning Path", path_id)

    # Categories
    categories = frappe.get_all(
        "LMS Module Category",
        filters={"parent": path_id, "parenttype": "LMS Learning Path"},
        fields=["category"]
    )
    category_list = [c.category for c in categories]

    # Modules in order
    if version:
        import json
        version_doc = frappe.db.get_value("LMS LP Version", {"parent": path_id, "version": version}, "content_snapshot")
        if version_doc:
            snapshot = json.loads(version_doc)
            path_courses = []
            for m in snapshot.get("modules", []):
                # Ensure object notation matches what the loop expects
                path_courses.append(frappe._dict({
                    "module": m.get("module"),
                    "sequence_order": m.get("sequence_order")
                }))
        else:
            path_courses = []
    else:
        path_courses = frappe.get_all(
            "LMS Learning Path Course",
            filters={"parent": path_id},
            fields=["module", "sequence_order"],
            order_by="sequence_order asc"
        )

    modules = []
    for pc in path_courses:
        mod = frappe.get_value(
            "LMS Module",
            pc.module,
            ["name", "module_name", "description", "image", "duration"],
            as_dict=True
        )
        if mod:
            # Count lessons
            lesson_count_res = frappe.db.sql("""
                SELECT count(name)
                FROM `tabLMS Module Lesson Child`
                WHERE parent = %s AND parenttype = 'LMS Module'
            """, (mod.name,))
            mod["lesson_count"] = lesson_count_res[0][0] if lesson_count_res else 0
            mod["completed_learners"] = 0  # populated below
            modules.append(mod)

    total_duration = sum(m.get("duration") or 0 for m in modules)
    hours = total_duration // 60
    mins = total_duration % 60
    duration_str = ""
    if hours > 0:
        duration_str += f"{hours} hrs "
    if mins > 0 or hours == 0:
        duration_str += f"{mins} min"

    # ── Resolve assigned learners from LMS Learning Path Assignment ──────────
    assignments = frappe.get_all(
        "LMS Learning Path Assignment",
        filters={"learning_path": path_id},
        fields=["name", "assignment_type"]
    )

    assigned_users = set()

    for a in assignments:
        if a.assignment_type == "Everyone":
            # All active non-guest users
            lms_roles = frappe.get_all(
                "Has Role", filters={"role": ["in", ["LMS-Learner", "LMS-TL"]]}, fields=["parent"]
            )
            valid_users = [r.parent for r in lms_roles if r.parent not in ["Administrator", "Guest"]]
            all_users = frappe.get_all("User", filters={"enabled": 1, "name": ["in", valid_users or ["__nobody__"]]}, fields=["name"])
            for u in all_users:
                assigned_users.add(u.name)
        elif a.assignment_type == "Manual":
            lp_learners = frappe.get_all("LMS LP Assignment User", filters={"parent": a.name}, fields=["user"])
            for l in lp_learners:
                assigned_users.add(l.user)
        else:  # Team
            teams = frappe.get_all("LMS Assignment Team", filters={"parent": a.name}, fields=["team"])
            for t in teams:
                members = frappe.get_all("LMS Team Member", filters={"parent": t.team, "parentfield": "learners"}, fields=["user"])
                for m in members:
                    assigned_users.add(m.user)

    # ── Fetch ALL LP Trackers (anyone who has progress, assigned or not) ──────
    all_trackers = frappe.get_all(
        "LMS Learning Path Tracker",
        filters={"learning_path": path_id},
        fields=["name", "user", "status", "progress_percentage", "total_score"]
    )
    tracker_user_set = {t.user for t in all_trackers}

    # Union: assigned learners + anyone who has a tracker (started learning)
    all_relevant_users = assigned_users | tracker_user_set
    tracker_map = {t.user: t for t in all_trackers}

    total_assigned = len(all_relevant_users)
    passed_count = 0
    in_progress_count = 0
    failed_count = 0
    not_started_count = 0

    # Tracker status values: "Not started" | "In Progress" | "Completed" | "Failed"
    member_status = {}
    for user in all_relevant_users:
        t = tracker_map.get(user)
        if not t:
            not_started_count += 1
            member_status[user] = "Not Started"
        elif t.status == "Completed":
            passed_count += 1
            member_status[user] = "Completed"
        elif t.status == "In Progress":
            in_progress_count += 1
            member_status[user] = "In Progress"
        elif t.status == "Failed":
            failed_count += 1
            member_status[user] = "Failed"
        else:
            # "Not started" from tracker
            not_started_count += 1
            member_status[user] = "Not Started"

    pending_count = total_assigned - passed_count

    learners = {
        "total": total_assigned,
        "passed": passed_count,
        "pending": pending_count,
        "in_progress": in_progress_count,
        "failed": failed_count,
        "not_started": not_started_count,
    }

    # ── Per-module learner completion counts ─────────────────────────────────
    # Use LMS Path Module Progress (child table of LP Tracker) to count
    # how many learners completed each specific module in this path.
    module_name_list = [m["name"] for m in modules]
    if module_name_list and all_trackers:
        tracker_names = [t.name for t in all_trackers]
        module_progress_rows = frappe.get_all(
            "LMS Path Module Progress",
            filters={
                "parent": ["in", tracker_names],
                "module": ["in", module_name_list],
                "status": "Completed"
            },
            fields=["module", "parent"]
        )
        # Count distinct trackers (learners) who completed each module
        module_completed_map = {}
        seen = set()
        
        # Trackers that are entirely completed imply all modules are completed
        completed_tracker_names = {t.name for t in all_trackers if getattr(t, "status", None) == "Completed"}
        
        for tracker_name in completed_tracker_names:
            for mod_name in module_name_list:
                key = (mod_name, tracker_name)
                seen.add(key)
                module_completed_map[mod_name] = module_completed_map.get(mod_name, 0) + 1

        for row in module_progress_rows:
            key = (row.module, row.parent)
            if key not in seen:
                seen.add(key)
                module_completed_map[row.module] = module_completed_map.get(row.module, 0) + 1
        # Attach to modules
        for m in modules:
            m["completed_learners"] = module_completed_map.get(m["name"], 0)

    # Overall path completed learners (tracker status = Completed)
    path_completed_learners = passed_count

    # ── Department Performance ────────────────────────────────────────────────
    dept_map = {}
    if all_relevant_users:
        team_members_all = frappe.get_all(
            "LMS Team Member",
            filters={"user": ("in", list(all_relevant_users))},
            fields=["parent", "user"]
        )
        # Resolve team names
        team_ids = list({tm.parent for tm in team_members_all})
        team_name_map = {}
        if team_ids:
            teams_data = frappe.get_all("LMS Team", filters={"name": ["in", team_ids]}, fields=["name", "team_name"])
            team_name_map = {t.name: t.team_name for t in teams_data}

        for tm in team_members_all:
            dept = team_name_map.get(tm.parent, tm.parent)
            user = tm.user
            if dept not in dept_map:
                dept_map[dept] = {"total": 0, "passed": 0, "pending": 0, "in_progress": 0, "failed": 0}
            dept_map[dept]["total"] += 1
            st = member_status.get(user, "Not Started")
            if st == "Completed":
                dept_map[dept]["passed"] += 1
            elif st == "In Progress":
                dept_map[dept]["in_progress"] += 1
                dept_map[dept]["pending"] += 1
            elif st == "Failed":
                dept_map[dept]["failed"] += 1
                dept_map[dept]["pending"] += 1
            else:
                dept_map[dept]["pending"] += 1

    departments = []
    for dept, stats in dept_map.items():
        total_dept = stats["total"]
        progress = round((stats["passed"] / total_dept) * 100) if total_dept > 0 else 0
        departments.append({
            "name": dept,
            "total": total_dept,
            "passed": stats["passed"],
            "pending": stats["pending"],
            "in_progress": stats["in_progress"],
            "failed": stats["failed"],
            "progress": progress,
        })

    # Assessments (Quizzes inside Modules)
    from frappe.utils import flt
    assessments = []
    module_names = [m.get("name") for m in modules]
    if module_names:
        lessons = frappe.get_all("LMS Module Lesson Child", filters={"parent": ("in", module_names)}, fields=["parent as module", "lesson"])
        lesson_names = [l.lesson for l in lessons]
        if lesson_names:
            chapters = frappe.get_all("LMS Lesson Chapter", filters={"parent": ("in", lesson_names)}, fields=["parent as lesson", "chapter"])
            chapter_names = [c.chapter for c in chapters]
            if chapter_names:
                contents = frappe.get_all(
                    "LMS Chapter Content",
                    filters={"parent": ("in", chapter_names), "content_type": ("in", ["LMS Quiz Content", "LMS Assessment Content"])},
                    fields=["parent as chapter", "content_type", "content_reference"]
                )
                
                chap_to_less = {c.chapter: c.lesson for c in chapters}
                less_to_mod = {l.lesson: l.module for l in lessons}
                mod_name_map = {m.get("name"): m.get("module_name") or m.get("name") for m in modules}
                
                for cnt in contents:
                    lesson = chap_to_less.get(cnt.chapter)
                    module = less_to_mod.get(lesson)
                    
                    quiz_id = None
                    quiz_title = None
                    
                    if cnt.content_type == "LMS Quiz Content":
                        quiz_doc = frappe.get_value("LMS Quiz Content", cnt.content_reference, ["quiz", "title"], as_dict=True)
                        if quiz_doc and quiz_doc.quiz:
                            quiz_id = quiz_doc.quiz
                            quiz_title = quiz_doc.title
                    else:
                        quiz_doc = frappe.get_value("LMS Assessment Content", cnt.content_reference, ["assessment", "title"], as_dict=True)
                        if quiz_doc and quiz_doc.assessment:
                            quiz_id = quiz_doc.assessment
                            quiz_title = quiz_doc.title
                            
                    if quiz_id:
                        quiz_info = frappe.get_value("LMS Quiz", quiz_id, ["quiz_type"], as_dict=True)
                        
                        best_scores = {} # user -> {score, passed}
                        if all_relevant_users:
                            submissions = frappe.get_all(
                                "LMS Quiz Submission",
                                filters={
                                    "quiz": quiz_id,
                                    "user": ["in", list(all_relevant_users)]
                                },
                                fields=["user", "score", "passed"]
                            )
                            for sub in submissions:
                                user_key = sub.user
                                score = flt(sub.score)
                                if user_key not in best_scores or score > best_scores[user_key]["score"]:
                                    best_scores[user_key] = {"score": score, "passed": bool(sub.passed)}
                        
                        completed = len(best_scores)
                        avg_score = sum(val["score"] for val in best_scores.values()) / completed if completed > 0 else 0
                        pass_rate = sum(1 for val in best_scores.values() if val["passed"]) / completed * 100 if completed > 0 else 0
                        
                        assessments.append({
                            "id": cnt.content_reference,
                            "quiz_id": quiz_id,
                            "title": quiz_title or quiz_id,
                            "type": quiz_info.quiz_type if quiz_info else "Quiz Assessment",
                            "source": mod_name_map.get(module, module),
                            "avgScore": round(avg_score, 1),
                            "passRate": round(pass_rate, 1),
                            "completed": completed,
                            "expected": total_assigned,
                            "status": "Completed" if (completed >= total_assigned and total_assigned > 0) else ("Inprogress" if completed > 0 else "Not Started")
                        })

    # Version history for the settings panel
    version_history = []
    for v in (path.get("version_history") or []):
        version_history.append({
            "version": v.version,
            "is_current": v.is_current,
            "description": v.description or "",
            "date": str(v.date) if v.date else "",
            "author": v.author or "",
            "author_name": v.author_name or frappe.db.get_value("User", v.author, "full_name") or v.author or "",
        })

    return {
        "name": path.name,
        "path_name": path.path_name,
        "description": path.description,
        "image": path.image,
        "status": path.status,
        "is_mandatory": path.is_mandatory,
        "is_sequential": path.is_sequential,
        "enable_discussion": int(getattr(path, "enable_discussion", 0) or 0),
        "enable_certificate": int(path.enable_certificate or 0),
        "modified": str(path.modified),
        "categories": category_list,
        "category": category_list[0] if category_list else "",
        "modules": modules,
        "module_count": len(modules),
        "duration_str": duration_str.strip(),
        "total_duration": total_duration,
        "learners": learners,
        "departments": departments,
        "assessments": assessments,
        "path_completed_learners": path_completed_learners,
        "total_learners": total_assigned,
        "version_history": version_history,
    }


@frappe.whitelist()
def get_lp_learners(path_id):
    """
    Returns the full list of learners assigned to a learning path,
    with their progress from LMS Learning Path Tracker.
    Mirrors the get_module_learners pattern in module_management.py.
    """
    from frappe.utils import add_days, getdate, today

    # ── Resolve assigned learners from LP Assignments ─────────────────────────
    assignments = frappe.get_all(
        "LMS Learning Path Assignment",
        filters={"learning_path": path_id},
        fields=["name", "assignment_type", "duration", "creation"]
    )

    users = {}  # user -> {duration, creation}

    for a in assignments:
        duration = a.duration or 0
        creation_date = a.creation

        if a.assignment_type == "Everyone":
            lms_roles = frappe.get_all(
                "Has Role", filters={"role": ["in", ["LMS-Learner", "LMS-TL"]]}, fields=["parent"]
            )
            valid_users = [r.parent for r in lms_roles if r.parent not in ["Administrator", "Guest"]]
            all_users = frappe.get_all("User", filters={"enabled": 1, "name": ["in", valid_users or ["__nobody__"]]}, fields=["name"])
            for u in all_users:
                users.setdefault(u.name, {"duration": duration, "creation": creation_date})
        elif a.assignment_type == "Manual":
            lp_learners = frappe.get_all("LMS LP Assignment User", filters={"parent": a.name}, fields=["user"])
            for l in lp_learners:
                users.setdefault(l.user, {"duration": duration, "creation": creation_date})
        else:  # Team
            teams = frappe.get_all("LMS Assignment Team", filters={"parent": a.name}, fields=["team"])
            for t in teams:
                members = frappe.get_all("LMS Team Member", filters={"parent": t.team, "parentfield": "learners"}, fields=["user"])
                for m in members:
                    users.setdefault(m.user, {"duration": duration, "creation": creation_date})

    if not users:
        return {"learners": [], "stats": {"totalAssigned": 0, "notStarted": 0, "inProgress": 0, "completed": 0, "overdue": 0}}

    # ── Check if Path has any Assessment ──────────────────────────────────────
    has_assessment = False
    path_modules = frappe.get_all("LMS Learning Path Course", filters={"parent": path_id, "parenttype": "LMS Learning Path"}, fields=["module"])
    if path_modules:
        mod_names = [m.module for m in path_modules]
        lessons = frappe.get_all("LMS Module Lesson Child", filters={"parent": ("in", mod_names)}, fields=["lesson"])
        if lessons:
            chapters = frappe.get_all("LMS Lesson Chapter", filters={"parent": ("in", [l.lesson for l in lessons])}, fields=["chapter"])
            if chapters:
                contents = frappe.get_all(
                    "LMS Chapter Content",
                    filters={"parent": ("in", [c.chapter for c in chapters]), "content_type": ("in", ["LMS Quiz Content", "LMS Assessment Content"])},
                    fields=["name"], limit=1
                )
                if contents:
                    has_assessment = True

    # ── User info ──────────────────────────────────────────────────────────────
    user_docs = frappe.get_all("User", filters={"name": ["in", list(users.keys())]}, fields=["name", "full_name", "user_image"])
    user_map = {u.name: u for u in user_docs}

    # ── Team/department for each user ─────────────────────────────────────────
    team_members = frappe.get_all("LMS Team Member", filters={"user": ["in", list(users.keys())]}, fields=["user", "parent"])
    user_team_map = {u: [] for u in users.keys()}
    if team_members:
        team_names = frappe.get_all("LMS Team", filters={"name": ["in", [m.parent for m in team_members]]}, fields=["name", "team_name"])
        team_name_map = {t.name: t.team_name for t in team_names}
        for m in team_members:
            team_name = team_name_map.get(m.parent, m.parent)
            if team_name not in user_team_map[m.user]:
                user_team_map[m.user].append(team_name)
    user_team_map = {u: ", ".join(teams) for u, teams in user_team_map.items()}

    # ── LP Trackers for progress ──────────────────────────────────────────────
    trackers = frappe.get_all(
        "LMS Learning Path Tracker",
        filters={"learning_path": path_id, "user": ["in", list(users.keys())]},
        fields=["name", "user", "status", "progress_percentage", "total_score", "started_on", "completed_on", "modified"]
    )
    tracker_map = {t.user: t for t in trackers}

    stats = {"totalAssigned": len(users), "notStarted": 0, "inProgress": 0, "completed": 0, "overdue": 0}
    results = []
    seven_days_ago = add_days(today(), -7)

    for user, data in users.items():
        tracker = tracker_map.get(user)
        u_info = user_map.get(user)
        department = user_team_map.get(user, "")

        learner_info = {
            "name": user,
            "fullName": u_info.full_name if u_info else user,
            "avatar": u_info.user_image if u_info else None,
            "department": department,
            "progress": 0,
            "status": "Not Started",
            "score": None,
            "passingPercentage": 60,
            "dueDate": None,
            "lastActivity": None,
            "isOverdue": False,
            "isInactive": False,
            "needsAttention": False,
            "hasAssessment": has_assessment,
            "assignedDate": str(data.get("creation")) if data.get("creation") else None,
            "trackerName": tracker.name if tracker else None
        }

        # Due date calculation
        start_dt = getdate(tracker.started_on) if tracker and tracker.started_on else (getdate(data.get("creation")) if data.get("creation") else None)
        if data.get("duration") and start_dt:
            due = add_days(start_dt, data["duration"])
            learner_info["dueDate"] = str(due)
            if getdate(due) < getdate(today()) and (not tracker or tracker.status not in ["Completed"]):
                learner_info["isOverdue"] = True
                stats["overdue"] += 1
                learner_info["needsAttention"] = True

        if tracker:
            status_raw = tracker.status or "Not started"
            # Normalize "Not started" -> "Not Started"
            if status_raw.lower() == "not started":
                status_raw = "Not Started"
            learner_info["status"] = status_raw
            learner_info["progress"] = tracker.progress_percentage or 0
            learner_info["lastActivity"] = str(tracker.modified) if tracker.modified else None

            # Score from tracker
            if tracker.total_score is not None and float(tracker.total_score) >= 0:
                learner_info["score"] = float(tracker.total_score)

            if status_raw == "Completed":
                stats["completed"] += 1
            elif status_raw in ["In Progress", "Failed"]:
                stats["inProgress"] += 1
            else:
                stats["notStarted"] += 1

            if getdate(tracker.modified) < getdate(seven_days_ago) and status_raw != "Completed":
                learner_info["isInactive"] = True
                learner_info["needsAttention"] = True
        else:
            stats["notStarted"] += 1
            if data.get("creation") and getdate(data.get("creation")) < getdate(seven_days_ago):
                learner_info["isInactive"] = True
                learner_info["needsAttention"] = True

        results.append(learner_info)

    results.sort(
        key=lambda x: str(x.get("lastActivity") or x.get("assignedDate") or ""),
        reverse=True
    )

    return {"learners": results, "stats": stats}

@frappe.whitelist(allow_guest=False)
def duplicate_learning_path(path_name):
    if not path_name:
        frappe.throw("Path Name is required")
        
    original = frappe.get_doc("LMS Learning Path", path_name)
    
    import re
    # Extract base name by removing any trailing " (Copy)" or " (Copy X)"
    match = re.match(r'^(.*?)(?:\s*\(Copy(?:\s+\d+)?\))?$', original.path_name)
    base_name = match.group(1).strip() if match else original.path_name.strip()
    
    new_name = f"{base_name} (Copy)"
    counter = 1
    
    # Check if a path with this path_name already exists
    while frappe.db.exists("LMS Learning Path", {"path_name": new_name}):
        new_name = f"{base_name} (Copy {counter})"
        counter += 1
        
    # Create copy
    new_path = frappe.copy_doc(original)
    
    new_path.path_name = new_name
    new_path.status = "Draft"
    new_path.insert(ignore_permissions=True)
    
    return {"status": "success", "new_path_id": new_path.name}

@frappe.whitelist()
def get_learner_assignments(learner_email):
    """
    Returns lists of module names and learning path names that a specific learner
    is already assigned to, via ANY assignment type (Everyone, Team, or Manual).
    This is used by the Assign Learning modal to pre-check and disable already-assigned items.
    """
    assigned_modules = set()
    assigned_paths = set()

    # ----- Check which teams the learner belongs to -----
    learner_teams = frappe.get_all(
        "LMS Team Member",
        filters={"user": learner_email},
        fields=["parent"]
    )
    learner_team_ids = {t.parent for t in learner_teams}

    # ----- Module Assignments -----
    all_module_assignments = frappe.get_all(
        "LMS Module Assignment",
        fields=["name", "module", "assignment_type"]
    )
    module_assignment_names = [a.name for a in all_module_assignments]
    module_map = {a.name: a.module for a in all_module_assignments}

    # Everyone assignments — all learners are covered
    for a in all_module_assignments:
        if a.assignment_type == "Everyone":
            assigned_modules.add(a.module)

    # Manual assignments — check if learner's email is in child table
    if module_assignment_names:
        manual_records = frappe.get_all(
            "LMS Assignment User",
            filters={"parent": ["in", module_assignment_names], "user": learner_email},
            fields=["parent"]
        )
        for r in manual_records:
            assigned_modules.add(module_map.get(r.parent))

    # Team assignments — check if learner's team is in any assignment
    if learner_team_ids and module_assignment_names:
        team_records = frappe.get_all(
            "LMS Assignment Team",
            filters={"parent": ["in", module_assignment_names], "team": ["in", list(learner_team_ids)]},
            fields=["parent"]
        )
        for r in team_records:
            assigned_modules.add(module_map.get(r.parent))

    assigned_modules.discard(None)

    # ----- Learning Path Assignments -----
    all_path_assignments = frappe.get_all(
        "LMS Learning Path Assignment",
        fields=["name", "learning_path", "assignment_type"]
    )
    path_assignment_names = [a.name for a in all_path_assignments]
    path_map = {a.name: a.learning_path for a in all_path_assignments}

    for a in all_path_assignments:
        if a.assignment_type == "Everyone":
            assigned_paths.add(a.learning_path)

    if path_assignment_names:
        manual_lp_records = frappe.get_all(
            "LMS Assignment User",
            filters={"parent": ["in", path_assignment_names], "user": learner_email},
            fields=["parent"]
        )

        for r in manual_lp_records:
            assigned_paths.add(path_map.get(r.parent))

    if learner_team_ids and path_assignment_names:
        team_lp_records = frappe.get_all(
            "LMS Assignment Team",
            filters={"parent": ["in", path_assignment_names], "team": ["in", list(learner_team_ids)]},
            fields=["parent"]
        )
        for r in team_lp_records:
            assigned_paths.add(path_map.get(r.parent))

    assigned_paths.discard(None)

    return {
        "modules": list(assigned_modules),
        "learning_paths": list(assigned_paths)
    }

@frappe.whitelist()
def get_lp_assessment_analytics(path_id, quiz_id):
    import re
    
    # 1. Get all relevant users for this learning path
    assignments = frappe.get_all(
        "LMS Learning Path Assignment",
        filters={"learning_path": path_id},
        fields=["name", "assignment_type"]
    )
    assigned_users = set()
    for a in assignments:
        if a.assignment_type == "Everyone":
            lms_roles = frappe.get_all("Has Role", filters={"role": ["in", ["LMS-Learner", "LMS-TL"]]}, fields=["parent"])
            valid_users = [r.parent for r in lms_roles if r.parent not in ["Administrator", "Guest"]]
            all_users = frappe.get_all("User", filters={"enabled": 1, "name": ["in", valid_users or ["__nobody__"]]}, fields=["name"])
            assigned_users.update(u.name for u in all_users)
        elif a.assignment_type == "Manual":
            lp_learners = frappe.get_all("LMS LP Assignment User", filters={"parent": a.name}, fields=["user"])
            assigned_users.update(l.user for l in lp_learners)
        else:
            teams = frappe.get_all("LMS Assignment Team", filters={"parent": a.name}, fields=["team"])
            for t in teams:
                members = frappe.get_all("LMS Team Member", filters={"parent": t.team, "parentfield": "learners"}, fields=["user"])
                assigned_users.update(m.user for m in members)

    trackers = frappe.get_all("LMS Learning Path Tracker", filters={"learning_path": path_id}, fields=["user"])
    tracker_users = {t.user for t in trackers}
    all_relevant_users = assigned_users | tracker_users

    total_assigned = len(all_relevant_users)

    if not all_relevant_users:
        return {"stats": {"passRate": 0, "averageScore": 0, "completed": 0, "completedPct": 0}, "mostMissedQuestion": None, "analytics": []}

    submissions = frappe.get_all("LMS Quiz Submission", 
        filters={"quiz": quiz_id, "user": ["in", list(all_relevant_users)]},
        fields=["name", "user", "score", "passed", "quiz"]
    )
    
    if not submissions:
        return {"stats": {"passRate": 0, "averageScore": 0, "completed": 0, "completedPct": 0}, "mostMissedQuestion": None, "analytics": []}

    user_submissions = {}
    for sub in submissions:
        if sub.user not in user_submissions:
            user_submissions[sub.user] = []
        user_submissions[sub.user].append(sub)

    best_submissions = []
    total_score = 0
    passed_count = 0
    for user, subs in user_submissions.items():
        best_sub = max(subs, key=lambda s: s.score)
        best_submissions.append(best_sub)
        total_score += best_sub.score
        if best_sub.passed:
            passed_count += 1

    completed = len(best_submissions)
    passRate = round((passed_count / completed) * 100) if completed > 0 else 0
    averageScore = round(total_score / completed) if completed > 0 else 0
    completedPct = round((completed / total_assigned) * 100) if total_assigned > 0 else 0

    sub_names = [s.name for s in submissions] 
    responses = frappe.get_all("LMS Quiz Response", 
        filters={"parent": ["in", sub_names]},
        fields=["question", "is_correct", "selected_option"]
    )
    
    question_stats = {}
    for r in responses:
        q = r.question
        if q not in question_stats:
            question_stats[q] = {"total": 0, "correct": 0, "skipped": 0}
        question_stats[q]["total"] += 1
        if r.is_correct:
            question_stats[q]["correct"] += 1
        elif not r.selected_option:
            question_stats[q]["skipped"] += 1
            
    analytics = []
    most_missed = None
    highest_miss_rate = -1

    if question_stats:
        questions = frappe.get_all("LMS Quiz Question", 
            filters={"name": ["in", list(question_stats.keys())]},
            fields=["name", "question_text", "question_type"]
        )
        
        total_subs = len(submissions)
        for idx, q in enumerate(questions):
            stats = question_stats.get(str(q.name), {"total": 0, "correct": 0, "skipped": 0})
            missing_rows = max(0, total_subs - stats["total"])
            total_skipped = missing_rows + stats.get("skipped", 0)
            
            pass_pct = round((stats["correct"] / stats["total"]) * 100) if stats["total"] > 0 else 0
            skipped_rate = round((total_skipped / total_subs) * 100) if total_subs > 0 else 0
            
            total_answered = stats["total"] - stats.get("skipped", 0)
            wrong_answers = total_answered - stats["correct"]
            wrong_rate = round((wrong_answers / total_answered) * 100) if total_answered > 0 else 0
                
            raw_text = re.sub(r'<[^>]+>', '', q.question_text or '').strip()

            if wrong_rate > highest_miss_rate and wrong_rate > 0:
                highest_miss_rate = wrong_rate
                most_missed = {
                    "id": str(q.name),
                    "text": "Most Missed Question",
                    "question": raw_text[:97] + "..." if len(raw_text) > 100 else raw_text,
                    "percentage": wrong_rate,
                    "title": f"QUESTION {idx + 1}"
                }
                
            analytics.append({
                "id": str(q.name),
                "title": f"QUESTION {idx + 1}",
                "text": raw_text,
                "successRate": pass_pct,
                "skippedRate": skipped_rate,
                "tip": "Consider simplifying the wording or adding contextual callouts." if wrong_rate > 30 else None
            })

    return {
        "stats": {
            "passRate": passRate,
            "averageScore": averageScore,
            "completed": completed,
            "completedPct": completedPct
        },
        "mostMissedQuestion": most_missed,
        "analytics": analytics
    }
