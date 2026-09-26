import frappe
from frappe import _
from frappe.utils import get_url, add_days, today, getdate

@frappe.whitelist(allow_guest=True)
def get_learner_assigned_modules(user_id, limit=10, offset=0, categories=None, statuses=None, types=None, priorities=None):
    try:
        limit = int(limit)
        offset = int(offset)
    except:
        limit = 10
        offset = 0

    import json
    if categories and isinstance(categories, str):
        categories = json.loads(categories)
    if statuses and isinstance(statuses, str):
        statuses = json.loads(statuses)
    if types and isinstance(types, str):
        types = json.loads(types)
    if priorities and isinstance(priorities, str):
        priorities = json.loads(priorities)

    published_module_ids = frappe.get_all("LMS Module", filters={"status": "Published"}, pluck="name", ignore_permissions=True)
    modules = frappe.get_all("LMS Module", filters={"status": "Published"}, fields=["name", "module_name", "duration", "is_mandatory"], ignore_permissions=True)
    mod_dict = {m.name: m for m in modules}

    # Build category map
    module_names = [m.name for m in modules]
    mod_cat_dict = {}
    if module_names:
        categories_data = frappe.get_all(
            "LMS Module Category",
            filters={"parent": ["in", module_names], "parenttype": "LMS Module"},
            fields=["parent", "category"]
        )
        for c in categories_data:
            if c.parent not in mod_cat_dict:
                mod_cat_dict[c.parent] = []
            if c.category not in mod_cat_dict[c.parent]:
                mod_cat_dict[c.parent].append(c.category)

    # Build user's team memberships
    user_teams = [m.parent for m in frappe.get_all("LMS Team Member", filters={"user": user_id}, fields=["parent"], ignore_permissions=True)]

    # Resolve all modules assigned to this user via assignments
    assigned_modules = {}  # module_name -> assignment creation date

    all_assignments = frappe.get_all(
        "LMS Module Assignment",
        fields=["name", "module", "assignment_type", "duration", "creation"],
        ignore_permissions=True
    )

    for a in all_assignments:
        if a.module not in published_module_ids:
            continue
        is_assigned = False
        if a.assignment_type == "Everyone":
            is_assigned = True
        elif a.assignment_type == "Manual":
            is_assigned = bool(frappe.get_all(
                "LMS Assignment User",
                filters={"parent": a.name, "user": user_id},
                limit=1, ignore_permissions=True
            ))
        else:
            if user_teams:
                is_assigned = bool(frappe.get_all(
                    "LMS Assignment Team",
                    filters={"parent": a.name, "team": ["in", user_teams]},
                    limit=1, ignore_permissions=True
                ))

        if is_assigned and a.module not in assigned_modules:
            assigned_modules[a.module] = a.creation

    # Fetch existing tracker records so we have progress/status for assigned modules
    tracker_list = frappe.get_all(
        "LMS Module Tracker",
        filters={"user": user_id, "module": ["in", list(assigned_modules.keys())] if assigned_modules else ["in", [""]]},
        fields=["name", "module", "status", "progress_percentage", "started_on", "creation"],
        ignore_permissions=True
    )
    tracker_map = {t.module: t for t in tracker_list}

    # Also pick up any tracker records for modules NOT found via assignments
    # (e.g. modules where tracker was created but assignment was removed)
    extra_trackers = frappe.get_all(
        "LMS Module Tracker",
        filters={"user": user_id, "module": ["in", published_module_ids] if published_module_ids else ["in", [""]]},
        fields=["name", "module", "status", "progress_percentage", "started_on", "creation"],
        ignore_permissions=True
    )
    for t in extra_trackers:
        if t.module not in assigned_modules:
            assigned_modules[t.module] = t.creation
            tracker_map[t.module] = t

    results = []
    current_date = getdate(today())

    for module_name, assignment_creation in assigned_modules.items():
        mod = mod_dict.get(module_name)
        if not mod:
            continue

        tracker = tracker_map.get(module_name)

        # Determine status
        if tracker and tracker.status == "Unassigned":
            mod_status = "Unassigned"
        elif tracker:
            mod_status = tracker.status or "Not Started"
        else:
            mod_status = "Not Started"

        progress = int((tracker.progress_percentage or 0) if tracker else 0)

        due_date = "None"
        start = (tracker.started_on if tracker else None) or assignment_creation
        if start and mod.duration:
            due_dt = add_days(start, mod.duration)
            due_date_obj = getdate(due_dt)
            if mod_status not in ("Completed", "Unassigned") and current_date > due_date_obj:
                mod_status = "Overdue"

            if mod_status.lower() == "not started":
                due_date = "--"
            else:
                due_date = due_date_obj.strftime("%b %-d, %Y")

        cat_list = mod_cat_dict.get(mod.name, [])
        mod_category = " • ".join(cat_list) if cat_list else "General"
        is_mandatory = bool(mod.is_mandatory)
        mod_type = "Module"
        mod_priority = "Mandatory" if is_mandatory else "Optional"

        # Apply filters
        if categories and not any(c.lower() in mod_category.lower() for c in categories):
            continue
        if statuses and mod_status.lower() not in [s.lower() for s in statuses]:
            continue
        if types and mod_type.lower() not in [ty.lower() for ty in types]:
            continue
        if priorities and mod_priority.lower() not in [p.lower() for p in priorities]:
            continue

        results.append({
            "id": tracker.name if tracker else f"no-tracker-{module_name}",
            "moduleId": mod.name,
            "name": mod.module_name or mod.name,
            "category": mod_category,
            "progress": progress,
            "status": mod_status,
            "dueDate": due_date,
            "isMandatory": is_mandatory,
            "type": mod_type,
            "creation": tracker.creation if tracker else assignment_creation
        })

    # ── Learning Paths ───────────────────────────────────────────────────────
    published_lp_ids = frappe.get_all("LMS Learning Path", filters={"status": "Published"}, pluck="name", ignore_permissions=True)

    assigned_lps = {}  # lp_name -> creation

    all_lp_assignments = frappe.get_all(
        "LMS Learning Path Assignment",
        fields=["name", "learning_path", "assignment_type", "creation"],
        ignore_permissions=True
    )
    for a in all_lp_assignments:
        if a.learning_path not in published_lp_ids:
            continue
        is_assigned = False
        if a.assignment_type == "Everyone":
            is_assigned = True
        elif a.assignment_type == "Manual":
            is_assigned = bool(frappe.get_all(
                "LMS Assignment User",
                filters={"parent": a.name, "user": user_id},
                limit=1, ignore_permissions=True
            ))
        else:
            if user_teams:
                is_assigned = bool(frappe.get_all(
                    "LMS Assignment Team",
                    filters={"parent": a.name, "team": ["in", user_teams]},
                    limit=1, ignore_permissions=True
                ))
        if is_assigned and a.learning_path not in assigned_lps:
            assigned_lps[a.learning_path] = a.creation

    # Native LP learner enrollment
    for e in frappe.get_all("LMS Learning Path Learner", filters={"learner": user_id}, fields=["parent", "creation"], ignore_permissions=True):
        if e.parent in published_lp_ids and e.parent not in assigned_lps:
            assigned_lps[e.parent] = e.creation

    lp_tracker_list = frappe.get_all(
        "LMS Learning Path Tracker",
        filters={"user": user_id, "learning_path": ["in", list(assigned_lps.keys())] if assigned_lps else ["in", [""]]},
        fields=["name", "learning_path", "status", "progress_percentage", "started_on", "creation"],
        ignore_permissions=True
    )
    lp_tracker_map = {t.learning_path: t for t in lp_tracker_list}

    # Also pick up LP trackers not found via assignments
    extra_lp_trackers = frappe.get_all(
        "LMS Learning Path Tracker",
        filters={"user": user_id, "learning_path": ["in", published_lp_ids] if published_lp_ids else ["in", [""]]},
        fields=["name", "learning_path", "status", "progress_percentage", "started_on", "creation"],
        ignore_permissions=True
    )
    for t in extra_lp_trackers:
        if t.learning_path not in assigned_lps:
            assigned_lps[t.learning_path] = t.creation
            lp_tracker_map[t.learning_path] = t

    for lp_name, assignment_creation in assigned_lps.items():
        try:
            lp_doc = frappe.get_doc("LMS Learning Path", lp_name)
        except Exception:
            continue

        tracker = lp_tracker_map.get(lp_name)

        if tracker and tracker.status == "Unassigned":
            lp_status = "Unassigned"
        elif tracker:
            lp_status = tracker.status or "Not Started"
        else:
            lp_status = "Not Started"

        progress = int((tracker.progress_percentage or 0) if tracker else 0)
        is_mandatory = bool(lp_doc.get("is_mandatory", False))

        lp_category = "General"
        if hasattr(lp_doc, "category") and lp_doc.category:
            if isinstance(lp_doc.category, list) and len(lp_doc.category) > 0:
                cats = [getattr(c, "category", "") for c in lp_doc.category]
                lp_category = " • ".join([c for c in cats if c]) or "General"
            elif isinstance(lp_doc.category, str):
                lp_category = lp_doc.category

        mod_type = "Learning Path"
        mod_priority = "Mandatory" if is_mandatory else "Optional"

        if categories and not any(c.lower() in lp_category.lower() for c in categories): continue
        if statuses and lp_status.lower() not in [s.lower() for s in statuses]: continue
        if types and mod_type.lower() not in [ty.lower() for ty in types]: continue
        if priorities and mod_priority.lower() not in [p.lower() for p in priorities]: continue

        results.append({
            "id": tracker.name if tracker else f"no-tracker-lp-{lp_name}",
            "moduleId": lp_name,
            "name": lp_doc.path_name or lp_name,
            "category": lp_category,
            "progress": progress,
            "status": lp_status,
            "dueDate": "--",
            "isMandatory": is_mandatory,
            "type": mod_type,
            "creation": tracker.creation if tracker else assignment_creation
        })

    results.sort(key=lambda x: str(x.get("creation") or ""), reverse=True)

    total = len(results)
    paginated = results[offset:offset + limit]

    return {
        "items": paginated,
        "total": total,
        "limit": limit,
        "offset": offset
    }

@frappe.whitelist(allow_guest=True)

def get_learner_assessments(user_id, categories=None, statuses=None, types=None, priorities=None):
    try:
        published_module_ids = frappe.get_all("LMS Module", filters={"status": "Published"}, pluck="name")
        trackers = frappe.get_all("LMS Module Tracker", filters={"user": user_id, "module": ["in", published_module_ids] if published_module_ids else ["in", [""]]}, fields=["name", "module", "status"])
        
        import json
        if categories and isinstance(categories, str): categories = json.loads(categories)
        if statuses and isinstance(statuses, str): statuses = json.loads(statuses)
        if types and isinstance(types, str): types = json.loads(types)
        if priorities and isinstance(priorities, str): priorities = json.loads(priorities)
        
        # Fetch assigned modules to get their due dates
        assigned_data = get_learner_assigned_modules(user_id, limit=999999)
        due_date_map = {}
        for item in assigned_data.get("items", []):
            due_date_map[item.get("moduleId")] = item.get("dueDate", "--")

        results = []
        
        def build_assessments_for_module(mod, tracker_name, parent_due_date):
            """
            Build two lists of assessments:
            - lesson_assessments: quizzes/interactive content inside lesson chapters
            - final_assessments: quizzes in module.final_assessments table
            """
            lesson_quiz_map = {}  # quiz_name -> {"lesson_label": str, "content_type": str}
            for lesson_idx, lesson_row in enumerate(mod.lessons):
                lesson_doc = frappe.get_doc("LMS Lesson", lesson_row.lesson)
                lesson_label = lesson_doc.lesson_name or f"Lesson {lesson_idx + 1}"
                for chapter_row in lesson_doc.chapters:
                    chapter_doc = frappe.get_doc("LMS Chapter", chapter_row.chapter)
                    for content_row in chapter_doc.contents:
                        if content_row.content_type == "LMS Quiz Content":
                            qc = frappe.get_doc("LMS Quiz Content", content_row.content_reference)
                            if qc.quiz:
                                lesson_quiz_map[qc.quiz] = {"lesson_label": lesson_label, "content_type": "Quiz"}
                        elif content_row.content_type == "LMS Assessment Content":
                            ac = frappe.get_doc("LMS Assessment Content", content_row.content_reference)
                            if ac.assessment:
                                lesson_quiz_map[ac.assessment] = {"lesson_label": lesson_label, "content_type": "Assessment"}

            # Collect final assessment quiz names from the module's final_assessments table
            final_quiz_names = []
            for fa_row in getattr(mod, "final_assessments", []):
                if fa_row.assessment:
                    final_quiz_names.append(fa_row.assessment)

            # Fetch all submissions for these quizzes by this user
            all_quizzes = list(lesson_quiz_map.keys()) + final_quiz_names
            if all_quizzes:
                submissions = frappe.get_all(
                    "LMS Quiz Submission",
                    filters={"user": user_id, "quiz": ["in", all_quizzes]},
                    fields=["quiz", "score", "passed", "extra_attempts_granted"]
                )
            else:
                submissions = []

            # Aggregate submissions per quiz
            ass_dict = {}
            for s in submissions:
                extra = s.get("extra_attempts_granted") or 0
                if s.quiz not in ass_dict:
                    ass_dict[s.quiz] = {
                        "best_score": s.score, 
                        "attempts": 1, 
                        "passed": bool(s.passed), 
                        "extra_attempts": extra,
                        "has_pending": False
                    }
                else:
                    ass_dict[s.quiz]["attempts"] += 1
                    ass_dict[s.quiz]["extra_attempts"] += extra
                    
                    # Safely handle None scores for comparison
                    curr_score = s.score if s.score is not None else 0
                    best_score = ass_dict[s.quiz]["best_score"] if ass_dict[s.quiz]["best_score"] is not None else 0
                    if curr_score > best_score:
                        ass_dict[s.quiz]["best_score"] = s.score
                        
                    if s.passed:
                        ass_dict[s.quiz]["passed"] = True

                if s.score is None:
                    ass_dict[s.quiz]["has_pending"] = True

            def build_assessment_entry(quiz_name, lesson_label, assessment_type):
                """
                assessment_type: "Quiz", "Assessment", or "Interactive"
                - Interactive: no pass score, no attempts limit, result is Completed/Not Started
                """
                data = ass_dict.get(quiz_name, {"best_score": 0, "attempts": 0, "passed": False, "extra_attempts": 0, "has_pending": False})
                quiz = frappe.get_doc("LMS Quiz", quiz_name)
                max_att = quiz.max_attempts or 0
                if max_att > 0:
                    max_att += data.get("extra_attempts", 0)
                    
                is_interactive = not quiz.is_passing_required and max_att == 0
                pass_pct = quiz.passing_percentage if quiz.is_passing_required else None

                # Override type to Interactive if quiz has no passing requirement and no max attempts
                display_type = "Interactive" if is_interactive else assessment_type

                best_score_raw = data.get("best_score", 0)
                total_score = quiz.total_score or 0
                if total_score > 0:
                    best_score_pct = int(round(((best_score_raw or 0) / total_score) * 100))
                else:
                    best_score_pct = int(round(best_score_raw or 0))

                if is_interactive:
                    # Interactive: result is Completed if submitted, else Not Started
                    if data["attempts"] > 0:
                        res = "Completed"
                    else:
                        res = "Not Started"
                    return {
                        "id": quiz_name,
                        "title": quiz.title,
                        "type": "Interactive",
                        "bestScore": best_score_pct,
                        "passScore": "--",
                        "attempts": "--",
                        "attemptsUsed": data["attempts"],
                        "maxAttempts": 0,
                        "result": res,
                        "lesson": lesson_label,
                        "dueDate": parent_due_date if parent_due_date and parent_due_date != "None" and res != "Not Started" else "--"
                    }

                if data["attempts"] == 0:
                    res = "Not Started"
                elif quiz.evaluation_method == "Manual review" and data.get("has_pending"):
                    res = "Awaiting evaluation"
                elif data["passed"]:
                    res = "Passed"
                else:
                    res = "Failed"

                return {
                    "id": quiz_name,
                    "title": quiz.title,
                    "type": display_type,
                    "bestScore": best_score_pct,
                    "passScore": pass_pct if pass_pct is not None else "--",
                    "attempts": f"{data['attempts']}/{max_att}" if max_att > 0 else str(data["attempts"]),
                    "attemptsUsed": data["attempts"],
                    "maxAttempts": max_att,
                    "result": res,
                    "lesson": lesson_label,
                    "dueDate": parent_due_date if parent_due_date and parent_due_date != "None" and res != "Not Started" else "--"
                }

            lesson_assessments = [
                build_assessment_entry(q, lesson_quiz_map[q]["lesson_label"], lesson_quiz_map[q]["content_type"])
                for q in lesson_quiz_map
            ]
            final_assessments = [
                build_assessment_entry(q, "Final Assessment", "Assessment")
                for q in final_quiz_names
            ]

            # Required score: from module's certificate passing percentage
            required_score = getattr(mod, "certificate_passing_percentage", None) or 0

            # Retake used: sum of (attemptsUsed - 1) over sum of (maxAttempts - 1) across all assessments
            retake_used = 0
            retake_max = 0
            has_limits = False
            for a in lesson_assessments + final_assessments:
                if a.get("maxAttempts", 0) > 0:
                    has_limits = True
                    retake_max += max(0, a["maxAttempts"] - 1)
                    retake_used += max(0, a["attemptsUsed"] - 1)
            
            if not has_limits:
                retake_used = "--"
                retake_max = "--"
            
            return lesson_assessments, final_assessments, required_score, retake_used, retake_max

        for t in trackers:
            mod = frappe.get_doc("LMS Module", t.module)

            # Retrieve module's due date to pass to its assessments
            module_due_date = due_date_map.get(mod.name, "--")
            lesson_assessments, final_assessments, required_score, retake_used, retake_max = build_assessments_for_module(mod, t.name, module_due_date)
            all_assessments = lesson_assessments + final_assessments

            # Determine module result dynamically from all assessments
            assessments_for_status = all_assessments
            if not assessments_for_status:
                mod_status = t.status or "Not Started"
            elif all(a["result"] == "Passed" for a in assessments_for_status):
                mod_status = "Completed"
            elif all(a["result"] == "Not Started" for a in assessments_for_status):
                mod_status = "Not Started"
            elif any(a["result"] == "Failed" for a in assessments_for_status):
                mod_status = "Failed"
            elif any(a["result"] == "Needs attention" for a in assessments_for_status):
                mod_status = "Needs attention"
            elif all(a["result"] == "Not Started" for a in assessments_for_status):
                mod_status = "Not Started"
            else:
                mod_status = "In Progress"

            mod_overall = (
                sum(a["bestScore"] for a in all_assessments) / len(all_assessments)
                if all_assessments else 0
            )

            # Average pass score (only assessments with a real pass score, not "--")
            scored_assessments = [a for a in all_assessments if a["passScore"] != "--"]
            mod_avg_pass = (
                sum(a["passScore"] for a in scored_assessments) / len(scored_assessments)
                if scored_assessments else None
            )

            # Highest attempts used / max across all assessments (excluding Interactive with maxAttempts=0)
            limited_assessments = [a for a in all_assessments if a["maxAttempts"] > 0]
            if limited_assessments:
                highest = max(limited_assessments, key=lambda a: a["attemptsUsed"])
                mod_max_attempts_str = f"{highest['attemptsUsed']}/{highest['maxAttempts']}"
            else:
                mod_max_attempts_str = "--"

            paths = frappe.get_all("LMS Learning Path Course", filters={"module": mod.name}, fields=["parent"])
            path_name = paths[0].parent if paths else None
            
            if mod.name == "Corporate Compliance":
                print(f"DEBUG CC: paths={paths}, mod.name={mod.name}")

            if path_name:
                path_item = next((r for r in results if r["title"] == path_name and r["type"] == "Learning Path"), None)
                if not path_item:
                    path_doc = frappe.get_doc("LMS Learning Path", path_name)
                    path_cat = "General"
                    if getattr(path_doc, "category", None):
                        path_cat = path_doc.category[0].category if isinstance(path_doc.category, list) else path_doc.category

                    path_item = {
                        "id": path_name,
                        "title": path_name,
                        "type": "Learning Path",
                        "category": path_cat,
                        "status": "In Progress",
                        "image": getattr(path_doc, "image", None),
                        "modules": [],
                        "lessonsCount": 0,
                        "assessmentsCount": 0
                    }
                    results.append(path_item)

                path_item["modules"].append({
                    "id": mod.name,
                    "title": mod.module_name,
                    "status": mod_status,
                    "assessments": all_assessments,
                    "lessonAssessments": lesson_assessments,
                    "finalAssessments": final_assessments,
                    "lessonsCount": len(mod.lessons),
                    "assessmentsCount": len(all_assessments),
                    "overallScore": int(mod_overall),
                    "avgPassScore": int(mod_avg_pass) if mod_avg_pass is not None else "--",
                    "maxAttemptsStr": mod_max_attempts_str,
                    "requiredScore": required_score,
                    "retakeUsed": retake_used,
                    "retakeMax": retake_max
                })
                path_item["lessonsCount"] += len(mod.lessons)
                path_item["assessmentsCount"] += len(all_assessments)
            else:
                mod_cat = "General"
                if getattr(mod, "category", None):
                    mod_cat = mod.category[0].category if isinstance(mod.category, list) else mod.category

                results.append({
                    "id": mod.name,
                    "title": mod.module_name,
                    "type": "Module",
                    "category": mod_cat,
                    "status": mod_status,
                    "image": getattr(mod, "image", None),
                    "lessonsCount": len(mod.lessons),
                    "assessmentsCount": len(all_assessments),
                    "assessments": all_assessments,
                    "lessonAssessments": lesson_assessments,
                    "finalAssessments": final_assessments,
                    "overallScore": int(mod_overall),
                    "avgPassScore": int(mod_avg_pass) if mod_avg_pass is not None else "--",
                    "maxAttemptsStr": mod_max_attempts_str,
                    "requiredScore": required_score,
                    "retakeUsed": retake_used,
                    "retakeMax": retake_max
                })

                
        # Apply filters
        if categories:
            results = [r for r in results if any(c.lower() in r["category"].lower() for c in categories)]
        if statuses:
            results = [r for r in results if r["status"].lower() in [s.lower() for s in statuses]]
        if types:
            results = [r for r in results if r["type"].lower() in [ty.lower() for ty in types]]
            
        total_assessments_completed = 0
        total_assessments_total = 0
        score_sum = 0
        score_count = 0
        quiz_score_sum = 0
        quiz_count = 0
        qa_score_sum = 0
        qa_count = 0
        
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
                    r["status"] = "In Progress"
                    
            for m in mods:
                for a in m.get("assessments", []):
                    total_assessments_total += 1
                    if a["result"] in ("Passed", "Completed"):
                        total_assessments_completed += 1
                    if a["result"] == "Not Started":
                        continue
                    score = a.get("bestScore", 0) or 0
                    score_sum += score
                    score_count += 1
                    atype = (a.get("type") or "").lower()
                    if "quiz" in atype or atype == "quiz":
                        quiz_score_sum += score
                        quiz_count += 1
                    elif "qa" in atype or "assessment" in atype or "interactive" in atype:
                        qa_score_sum += score
                        qa_count += 1
                    
        stats = {
            "assessmentsCompleted": total_assessments_completed,
            "assessmentsTotal": total_assessments_total,
            "averageScore": int(score_sum / score_count) if score_count > 0 else 0,
            "quizPerformance": int(quiz_score_sum / quiz_count) if quiz_count > 0 else 0,
            "quizCount": quiz_count,
            "qaPerformance": int(qa_score_sum / qa_count) if qa_count > 0 else 0,
            "qaCount": qa_count,
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
            fields=["name", "score", "passed", "creation", "time_taken"],
            order_by="creation asc"
        )
        
        learner_name = frappe.db.get_value("User", user_id, "full_name") or user_id
        
        # Determine source
        source_title = "Unknown"
        source_type = "Unknown"
        
        mod_name = frappe.db.get_value("LMS Module Assessment", {"assessment": quiz_name}, "parent")
        if not mod_name:
            qc = frappe.db.get_value("LMS Quiz Content", {"quiz": quiz_name}, "name")
            ac = frappe.db.get_value("LMS Assessment Content", {"assessment": quiz_name}, "name")
            ref_name = qc or ac
            if ref_name:
                chap_name = frappe.db.get_value("LMS Chapter Content", {"content_reference": ref_name}, "parent")
                if chap_name:
                    lesson_name = frappe.db.get_value("LMS Lesson Chapter", {"chapter": chap_name}, "parent")
                    if lesson_name:
                        mod_name = frappe.db.get_value("LMS Module Lesson Child", {"lesson": lesson_name}, "parent")
                        
        if mod_name:
            mod_title = frappe.db.get_value("LMS Module", mod_name, "module_name")
            source_title = mod_title or mod_name
            source_type = "Module"
        
        history = []
        for i, s in enumerate(submissions):
            attempt_num = i + 1
            t = int(s.time_taken or 0)
            m, sec = divmod(t, 60)
            dur_str = f"{m}m {sec}s" if m > 0 else f"{sec}s"
            
            history.insert(0, {
                "id": s.name,
                "attempt": f"Attempt {attempt_num}",
                "score": f"{int(s.score)}% {'Passed' if s.passed else 'Failed'}",
                "date": s.creation.strftime("%b %-d, %Y"),
                "duration": dur_str,
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
                fields=["question", "is_correct", "selected_option", "manual_score", "evaluation_data"],
                order_by="idx asc"
            )
            
            import re
            import json
            for idx, r in enumerate(responses):
                q_doc = frappe.get_doc("LMS Quiz Question", r.question)
                is_correct = bool(r.is_correct)
                if is_correct:
                    correct_count += 1
                else:
                    incorrect_count += 1
                    
                q_text = re.sub('<[^<]+>', '', q_doc.question_text or '')
                
                requires_manual = False
                if q_doc.question_type == "Scenario Based":
                    requires_manual = True
                elif q_doc.question_type == "Fill in the Blank" and len(q_doc.options) == 0:
                    requires_manual = True
                    
                max_score = 5
                if requires_manual and q_doc.options:
                    max_score = sum(int(opt.score) if opt.score else 5 for opt in q_doc.options)
                elif not requires_manual:
                    max_score = int(q_doc.score) if q_doc.score else 1
                
                eval_data = {}
                if r.evaluation_data:
                    try:
                        eval_data = json.loads(r.evaluation_data)
                    except:
                        pass
                
                correct_answer = ""
                if not requires_manual:
                    correct_opts = [re.sub('<[^<]+>', '', opt.option_text or '').strip() for opt in q_doc.options if opt.is_correct]
                    if correct_opts:
                        correct_answer = ", ".join(correct_opts)

                questions_performance.append({
                    "id": r.question,
                    "index": idx + 1,
                    "text": q_text.strip(),
                    "isCorrect": is_correct,
                    "learnerResponse": r.selected_option or "",
                    "correctAnswer": correct_answer,
                    "managerFeedback": eval_data.get("feedback", ""),
                    "manualScore": r.manual_score or 0,
                    "maxScore": max_score,
                    "requiresManual": requires_manual
                })
                
        def format_time(seconds):
            if not seconds:
                return "--"
            seconds = int(seconds)
            if seconds < 60:
                return f"{seconds} sec"
            m, s = divmod(seconds, 60)
            if s > 0:
                return f"{m} min {s} sec"
            return f"{m} min"
            
        stats = {
            "questions": len(quiz.questions) if hasattr(quiz, "questions") else (correct_count + incorrect_count or 20),
            "correct": correct_count,
            "incorrect": incorrect_count,
            "attempts": total_attempts,
            "maxAttempts": getattr(quiz, "max_attempts", 0),
            "bestScore": f"{int(best_score)}%" if submissions else "--",
            "passingScore": getattr(quiz, "passing_percentage", "--"),
            "timeTaken": format_time(latest_sub.time_taken) if latest_sub and latest_sub.get("time_taken") else ("--" if not submissions else "14 min"),
            "timeLimitMins": getattr(quiz, "time_limit_mins", 0),
            "dateTaken": latest_sub.creation.strftime("%b %-d, %Y") if latest_sub else "--"
        }
        
        return {
            "stats": stats,
            "history": history,
            "questions": questions_performance,
            "title": quiz.title,
            "learnerName": learner_name,
            "sourceTitle": source_title,
            "sourceType": source_type
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
            {"label": "In Progress", "color": "var(--status-in-progress-fg)", "bg": "var(--status-in-progress-bg)"},
            {"label": "Not Started", "color": "#595F69", "bg": "#ECEDEF"},
            {"label": "Needs attention", "color": "#D97706", "bg": "#F5E9DB"},
            {"label": "Failed", "color": "#DC2626", "bg": "#FEE2E2"}
        ]
    }
@frappe.whitelist()
def unassign_learning(user_id, item_id, item_type):
    import hashlib
    if item_type == "Learning Path":
        trackers = frappe.get_all("LMS Learning Path Tracker", filters={"learning_path": item_id, "user": user_id})
        for t in trackers:
            frappe.db.set_value("LMS Learning Path Tracker", t.name, "status", "Unassigned")
        
        # Remove from Manual Learning Path Assignments
        assignments = frappe.get_all("LMS Learning Path Assignment", filters={"learning_path": item_id, "assignment_type": "Manual"})
        for a in assignments:
            frappe.db.sql("""
                DELETE FROM `tabLMS Assignment User`
                WHERE parent = %s AND user = %s
            """, (a.name, user_id))
            
        # Also remove from native LMS Learning Path if assigned directly
        lp_doc = frappe.get_doc("LMS Learning Path", item_id)
        if lp_doc.get("path_access") == "Manual":
            frappe.db.sql("""
                DELETE FROM `tabLMS Learning Path Learner`
                WHERE parent = %s AND learner = %s
            """, (item_id, user_id))
            
    else:
        # 1. Instead of deleting, mark any existing Module Tracker as Unassigned
        trackers = frappe.get_all("LMS Module Tracker", filters={"user": user_id, "module": item_id})
        if trackers:
            for t in trackers:
                frappe.db.set_value("LMS Module Tracker", t.name, "status", "Unassigned")
        else:
            # Insert sentinel tracker so the module is hidden even if assigned via Learning Path
            excl_name = "EXCL-" + hashlib.md5(f"{user_id}:{item_id}".encode()).hexdigest()[:20]
            now = frappe.utils.now()
            frappe.db.sql("""
                INSERT INTO `tabLMS Module Tracker`
                    (name, user, module, status, progress_percentage, creation, modified, owner, modified_by, docstatus)
                VALUES (%s, %s, %s, 'Unassigned', 0, %s, %s, %s, %s, 0)
                ON DUPLICATE KEY UPDATE status = 'Unassigned', modified = %s
            """, (excl_name, user_id, item_id, now, now, user_id, user_id, now))

        assignments = frappe.get_all("LMS Module Assignment", filters={"module": item_id, "assignment_type": "Manual"})
        for a in assignments:
            frappe.db.sql("""
                DELETE FROM `tabLMS Assignment User`
                WHERE parent = %s AND user = %s
            """, (a.name, user_id))

    frappe.db.commit()
    return {"status": "success"}

@frappe.whitelist()
def reassign_learning(user_id, item_id, item_type):
    """Re-activates a previously unassigned tracker by setting its status back to Not Started."""
    if item_type == "Learning Path":
        trackers = frappe.get_all("LMS Learning Path Tracker", filters={"learning_path": item_id, "user": user_id, "status": "Unassigned"})
        for t in trackers:
            frappe.db.set_value("LMS Learning Path Tracker", t.name, "status", "Not Started")
    else:
        trackers = frappe.get_all("LMS Module Tracker", filters={"user": user_id, "module": item_id, "status": "Unassigned"})
        for t in trackers:
            frappe.db.set_value("LMS Module Tracker", t.name, "status", "Not Started")

    frappe.db.commit()
    return {"status": "success"}

@frappe.whitelist()
def get_reminder_activity(user_id, assessment_id=None):
    """
    Returns automated and admin reminder counts/dates for a user (and optionally a specific assessment).
    Uses LMS Notification Log for automated reminders and a custom admin_reminder field for manual ones.
    """
    from frappe.utils import today, add_days, getdate, format_date

    # Automated reminders: from LMS Notification Log
    filters = {"user": user_id, "status": "Sent"}
    auto_logs = frappe.get_all(
        "LMS Notification Log",
        filters=filters,
        fields=["name", "sent_on", "rule_triggered"],
        order_by="sent_on desc"
    )

    automated_count = len(auto_logs)

    # Admin reminders: logs where rule_triggered is None/empty (manual sends)
    admin_logs = [l for l in auto_logs if not l.get("rule_triggered")]
    auto_logs_real = [l for l in auto_logs if l.get("rule_triggered")]

    automated_count = len(auto_logs_real)
    admin_count = len(admin_logs)
    last_admin_date = None
    if admin_logs:
        last_admin_date = admin_logs[0].sent_on
        if last_admin_date:
            last_admin_date = frappe.utils.formatdate(str(last_admin_date)[:10], "d MMM")

    # Check if an automated reminder is scheduled for tomorrow
    # by checking LMS Reminder Rule trigger windows
    scheduled_tomorrow = False
    reminder_rules = frappe.get_all(
        "LMS Reminder Rule",
        fields=["trigger_days", "trigger_type"]
    ) if frappe.db.exists("DocType", "LMS Reminder Rule") else []
    # Simple heuristic: if any rule triggers, flag it
    if reminder_rules:
        scheduled_tomorrow = any(r.get("trigger_days") == 1 for r in reminder_rules)

    return {
        "automatedCount": automated_count,
        "adminCount": admin_count,
        "lastAdminDate": last_admin_date,
        "scheduledTomorrow": scheduled_tomorrow,
    }


@frappe.whitelist()
def send_priority_reminder(user_id, assessment_id, learner_name=None):
    """
    Sends a priority (admin) reminder to a learner and logs it.
    """
    try:
        user_doc = frappe.get_doc("User", user_id)
        full_name = user_doc.full_name or user_doc.first_name or user_id

        # Log the admin reminder
        log = frappe.get_doc({
            "doctype": "LMS Notification Log",
            "user": user_id,
            "rule_triggered": None,
            "message_sent": f"Priority reminder sent by admin for assessment {assessment_id}",
            "sent_on": frappe.utils.now(),
            "status": "Sent"
        })
        log.insert(ignore_permissions=True)
        frappe.db.commit()

        # In a real app, send actual email here:
        # frappe.sendmail(recipients=[user_doc.email], ...)

        return {"status": "success", "message": f"Priority reminder sent to {full_name}"}
    except Exception as e:
        frappe.log_error("send_priority_reminder failed", str(e))
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def send_learning_reminder(user_id, item_id, item_type):
    # In a real app, this would send an email or notification
    # frappe.sendmail(...)
    return {"status": "success", "message": "Reminder sent successfully"}


@frappe.whitelist()
def get_team_lead_for_user(user_id):
    """
    Looks up the LMS Team Lead(s) for a learner's team and returns the lead's profile info.
    Also returns the automated reminder count to power the Lumi recommendation.
    """
    # Find the team the user belongs to
    team_member = frappe.get_all(
        "LMS Team Member",
        filters={"user": user_id},
        fields=["parent"],
        limit=1
    )

    lead_info = None
    team_name = None

    if team_member:
        team_name_val = team_member[0].parent
        # Look up team leads for that team
        team_leads = frappe.get_all(
            "LMS Team Lead",
            filters={"parent": team_name_val},
            fields=["user"],
            limit=1
        )
        if team_leads:
            lead_user = team_leads[0].user
            lead_doc = frappe.get_doc("User", lead_user)
            team_doc = frappe.get_doc("LMS Team", team_name_val)
            team_name = team_doc.team_name or team_name_val

            # Get lead designation from HR or fallback
            designation = getattr(lead_doc, "designation", None) or "Team Lead"

            lead_info = {
                "user": lead_user,
                "name": lead_doc.full_name or lead_doc.first_name or lead_user,
                "avatar": lead_doc.user_image or None,
                "designation": designation,
                "team": team_name,
            }

    # Get automated reminder count for Lumi recommendation
    auto_logs = frappe.get_all(
        "LMS Notification Log",
        filters={"user": user_id, "status": "Sent"},
        fields=["rule_triggered"]
    )
    automated_count = len([l for l in auto_logs if l.get("rule_triggered")])

    return {
        "lead": lead_info,
        "automatedCount": automated_count,
    }


@frappe.whitelist()
def escalate_to_lead(user_id, assessment_id, reason, note=None):
    """
    Logs an escalation to the team lead.
    """
    try:
        user_doc = frappe.get_doc("User", user_id)
        learner_name = user_doc.full_name or user_doc.first_name or user_id

        # Log escalation as a notification log entry
        log = frappe.get_doc({
            "doctype": "LMS Notification Log",
            "user": user_id,
            "rule_triggered": None,
            "message_sent": f"Escalation to team lead | Reason: {reason} | Note: {note or ''} | Assessment: {assessment_id}",
            "sent_on": frappe.utils.now(),
            "status": "Sent"
        })
        log.insert(ignore_permissions=True)
        frappe.db.commit()

        return {"status": "success", "message": f"Escalation logged for {learner_name}"}
    except Exception as e:
        frappe.log_error("escalate_to_lead failed", str(e))
        return {"status": "error", "message": str(e)}

@frappe.whitelist()
def get_assessment_attempts(user_id, quiz_name):
    submissions = frappe.get_all(
        "LMS Quiz Submission",
        filters={"user": user_id, "quiz": quiz_name},
        fields=["name", "score", "passed", "creation", "extra_attempts_granted", "grant_reason", "enrollment", "time_taken"],
        order_by="creation asc"
    )
    
    quiz = frappe.get_doc("LMS Quiz", quiz_name)
    total_score = quiz.total_score or 0
    
    history = []
    for idx, s in enumerate(submissions):
        score_pct = int(round((s.score / total_score) * 100)) if total_score > 0 else int(round(s.score))
        
        duration_str = "--"
        if s.time_taken:
            mins = int(s.time_taken // 60)
            secs = int(s.time_taken % 60)
            if mins > 0:
                duration_str = f"{mins}m {secs}s"
            else:
                duration_str = f"{secs}s"
        
        history.append({
            "attempt": idx + 1,
            "score": score_pct,
            "passed": bool(s.passed),
            "duration": duration_str
        })
        
    return history

@frappe.whitelist()
def grant_additional_attempt(user_id, quiz_name, attempts, reason):
    submissions = frappe.get_all(
        "LMS Quiz Submission",
        filters={"user": user_id, "quiz": quiz_name},
        fields=["name", "extra_attempts_granted"],
        order_by="creation desc",
        limit=1
    )
    
    if not submissions:
        frappe.throw("Cannot grant additional attempt: No previous submissions found.")
        
    sub = frappe.get_doc("LMS Quiz Submission", submissions[0].name)
    current_extra = sub.extra_attempts_granted or 0
    sub.extra_attempts_granted = current_extra + int(attempts)
    sub.grant_reason = reason
    sub.save(ignore_permissions=True)
    frappe.db.commit()
    
    return {"status": "success"}
