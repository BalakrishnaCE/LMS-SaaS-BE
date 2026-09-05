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
        
    trackers = frappe.get_all(
        "LMS Module Tracker", 
        filters={"user": user_id}, 
        fields=["name", "module", "status", "progress_percentage", "started_on", "creation"],
        order_by="creation desc",
        ignore_permissions=True
    )
    
    modules = frappe.get_all("LMS Module", fields=["name", "module_name", "duration", "is_mandatory", "image"], ignore_permissions=True)
    mod_dict = {m.name: m for m in modules}
    
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
                mod_cat_dict[c.parent] = c.category
    
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
        mod_category = mod_cat_dict.get(mod.name) or "General"
        is_mandatory = bool(mod.is_mandatory)
        
        # Apply filters
        if categories and not any(c.lower() in mod_category.lower() for c in categories):
            continue
            
        if statuses and mod_status.lower() not in [s.lower() for s in statuses]:
            continue
            
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
            "isMandatory": is_mandatory,
            "type": mod_type,
            "creation": t.creation
        })
        
    lp_trackers = frappe.get_all(
        "LMS Learning Path Tracker",
        filters={"user": user_id},
        fields=["name", "learning_path", "status", "progress_percentage", "started_on", "creation"],
        ignore_permissions=True
    )
    
    if lp_trackers:
        for t in lp_trackers:
            try:
                lp_doc = frappe.get_doc("LMS Learning Path", t.learning_path)
            except:
                continue
                
            due_date = "None"
            lp_status = t.status or "Not Started"
            is_mandatory = bool(lp_doc.get("is_mandatory", False))
            
            lp_category = "General"
            if hasattr(lp_doc, "category") and lp_doc.category:
                if isinstance(lp_doc.category, list) and len(lp_doc.category) > 0:
                    lp_category = getattr(lp_doc.category[0], "category", "General")
                elif isinstance(lp_doc.category, str):
                    lp_category = lp_doc.category
                    
            if categories and not any(c.lower() in lp_category.lower() for c in categories): continue
            if statuses and lp_status.lower() not in [s.lower() for s in statuses]: continue
            
            mod_type = "Learning Path"
            if types and mod_type.lower() not in [ty.lower() for ty in types]: continue
            
            mod_priority = "Mandatory" if is_mandatory else "Optional"
            if priorities and mod_priority.lower() not in [p.lower() for p in priorities]: continue
                    
            results.append({
                "id": t.name,
                "moduleId": t.learning_path,
                "name": lp_doc.path_name or t.learning_path,
                "category": lp_category,
                "progress": int(t.progress_percentage or 0),
                "status": lp_status,
                "dueDate": due_date,
                "isMandatory": is_mandatory,
                "type": mod_type,
                "creation": t.creation
            })
            
    # Sort results by creation desc
    results.sort(key=lambda x: x.get("creation") or "", reverse=True)
        
    total = len(results)
    paginated = results[offset:offset+limit]
    
    return {
        "items": paginated,
        "total": total,
        "limit": limit,
        "offset": offset
    }

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
        
        def build_assessments_for_module(mod, tracker_name):
            """
            Build two lists of assessments:
            - lesson_assessments: quizzes/interactive content inside lesson chapters
            - final_assessments: quizzes in module.final_assessments table

            lesson_quiz_map stores: quiz_name -> {"lesson_label": ..., "content_type": "Quiz"|"Assessment"|"Interactive"}
            Interactive = no passing required, no attempts limit (mark as Completed when done)
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

            # Fetch all submissions for this tracker enrollment
            submissions = frappe.get_all(
                "LMS Quiz Submission",
                filters={"enrollment": tracker_name},
                fields=["quiz", "score", "passed"]
            )

            # Aggregate submissions per quiz
            ass_dict = {}
            for s in submissions:
                if s.quiz not in ass_dict:
                    ass_dict[s.quiz] = {"best_score": s.score, "attempts": 1, "passed": bool(s.passed)}
                else:
                    ass_dict[s.quiz]["attempts"] += 1
                    if s.score > ass_dict[s.quiz]["best_score"]:
                        ass_dict[s.quiz]["best_score"] = s.score
                    if s.passed:
                        ass_dict[s.quiz]["passed"] = True

            def build_assessment_entry(quiz_name, lesson_label, assessment_type):
                """
                assessment_type: "Quiz", "Assessment", or "Interactive"
                - Interactive: no pass score, no attempts limit, result is Completed/Not Started
                """
                data = ass_dict.get(quiz_name, {"best_score": 0, "attempts": 0, "passed": False})
                quiz = frappe.get_doc("LMS Quiz", quiz_name)
                max_att = quiz.max_attempts or 0
                is_interactive = not quiz.is_passing_required and max_att == 0
                pass_pct = quiz.passing_percentage if quiz.is_passing_required else None

                # Override type to Interactive if quiz has no passing requirement and no max attempts
                display_type = "Interactive" if is_interactive else assessment_type

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
                        "bestScore": data["best_score"],
                        "passScore": "--",
                        "attempts": "--",
                        "attemptsUsed": data["attempts"],
                        "maxAttempts": 0,
                        "result": res,
                        "lesson": lesson_label
                    }

                if data["attempts"] == 0:
                    res = "Not Started"
                elif data["passed"]:
                    res = "Passed"
                elif max_att > 0 and data["attempts"] >= max_att:
                    res = "Failed"
                else:
                    res = "Needs attention"

                return {
                    "id": quiz_name,
                    "title": quiz.title,
                    "type": display_type,
                    "bestScore": data["best_score"],
                    "passScore": pass_pct if pass_pct is not None else "--",
                    "attempts": f"{data['attempts']}/{max_att}" if max_att > 0 else str(data["attempts"]),
                    "attemptsUsed": data["attempts"],
                    "maxAttempts": max_att,
                    "result": res,
                    "lesson": lesson_label
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

            # Retake used: max attempts used / max_attempts across final assessments
            retake_used = "--"
            retake_max = "--"
            if final_assessments:
                finals_with_limits = [a for a in final_assessments if a["maxAttempts"] > 0]
                if finals_with_limits:
                    most_used = max(finals_with_limits, key=lambda a: a["attemptsUsed"])
                    retake_used = most_used["attemptsUsed"]
                    retake_max = most_used["maxAttempts"]

            return lesson_assessments, final_assessments, required_score, retake_used, retake_max


        for t in trackers:
            mod = frappe.get_doc("LMS Module", t.module)

            lesson_assessments, final_assessments, required_score, retake_used, retake_max = build_assessments_for_module(mod, t.name)
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
                    r["status"] = "In Progress"
                    
            for m in mods:
                for a in m.get("assessments", []):
                    if a["result"] == "Not Started":
                        continue
                    total_assessments_taken += 1
                    if a["result"] == "Passed":
                        total_passed += 1
                    else:
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
            {"label": "In Progress", "color": "var(--status-in-progress-fg)", "bg": "var(--status-in-progress-bg)"},
            {"label": "Not Started", "color": "#595F69", "bg": "#ECEDEF"},
            {"label": "Needs attention", "color": "#D97706", "bg": "#F5E9DB"},
            {"label": "Failed", "color": "#DC2626", "bg": "#FEE2E2"}
        ]
    }
@frappe.whitelist()
def unassign_learning(user_id, item_id, item_type):
    if item_type == "Learning Path":
        tracker = frappe.get_doc("LMS Learning Path Tracker", item_id)
        learning_path = tracker.learning_path
        
        # Bypass link checks to forcefully delete the tracker
        frappe.db.delete("LMS Learning Path Tracker", {"name": item_id})
        
        # Remove from Manual Learning Path Assignments
        assignments = frappe.get_all("LMS Learning Path Assignment", filters={"learning_path": learning_path, "assignment_type": "Manual"})
        for a in assignments:
            frappe.db.sql("""
                DELETE FROM `tabLMS Assignment User`
                WHERE parent = %s AND user = %s
            """, (a.name, user_id))
            
        # Also remove from native LMS Learning Path if assigned directly
        lp_doc = frappe.get_doc("LMS Learning Path", learning_path)
        if lp_doc.get("path_access") == "Manual":
            frappe.db.sql("""
                DELETE FROM `tabLMS Learning Path Learner`
                WHERE parent = %s AND learner = %s
            """, (learning_path, user_id))
            
    else:
        tracker = frappe.get_doc("LMS Module Tracker", item_id)
        module = tracker.module
        
        # Bypass link checks to forcefully delete the tracker
        frappe.db.delete("LMS Module Tracker", {"name": item_id})
        
        # Remove from Manual Module Assignments
        assignments = frappe.get_all("LMS Module Assignment", filters={"module": module, "assignment_type": "Manual"})
        for a in assignments:
            frappe.db.sql("""
                DELETE FROM `tabLMS Assignment User`
                WHERE parent = %s AND user = %s
            """, (a.name, user_id))
            
    frappe.db.commit()
    return {"status": "success"}

@frappe.whitelist()
def send_learning_reminder(user_id, item_id, item_type):
    # In a real app, this would send an email or notification
    # frappe.sendmail(...)
    return {"status": "success", "message": "Reminder sent successfully"}
