import frappe
import calendar
from collections import defaultdict
from frappe.utils import today, add_days, getdate, add_months, now
from lms.backend.api.manager.metrics import _get_team_member_emails

def _get_filter_for_user():
    user = frappe.session.user
    roles = frappe.get_roles(user)
    
    # LMS-TL (Team Lead) and LMS Manager are scoped to their own teams.
    # Check these BEFORE System Manager so that TLs who also have System Manager
    # are still correctly scoped when using the manager portal.
    if "LMS-TL" in roles or "LMS Manager" in roles:
        member_emails = _get_team_member_emails(user)
        if not member_emails:
            return [] # Returns empty list to indicate no data
        return member_emails

    if "System Manager" in roles or "LMS Admin" in roles:
        return None # No filter, return all data
        
    return [] # Default fallback

@frappe.whitelist(allow_guest=True)
def get_metrics_summary(learning_type="all"):
    user_filter = _get_filter_for_user()
    if user_filter == []:
        return {"month": {}, "year": {}}

    def get_data(timeframe):
        current_year = getdate(now()).year
        current_month = getdate(now()).month
        
        if timeframe == "year":
            intervals = [getdate(f"{current_year}-{m:02d}-28") for m in range(1, 13)]
        else:
            num_days = calendar.monthrange(current_year, current_month)[1]
            intervals = [
                getdate(f"{current_year}-{current_month:02d}-07"),
                getdate(f"{current_year}-{current_month:02d}-14"),
                getdate(f"{current_year}-{current_month:02d}-21"),
                getdate(f"{current_year}-{current_month:02d}-{num_days}")
            ]
        
        active_learners_history = []
        completion_rate_history = []
        overdue_assignments_history = []
        compliance_completion_history = []
        
        assignment_map = {}
        if learning_type in ["all", "modules"]:
            assignments = frappe.get_all("LMS Module Assignment", fields=["name", "module", "duration", "creation", "is_mandatory"])
            for a in assignments: assignment_map[a.module] = a
        if learning_type in ["all", "paths"]:
            assignments_p = frappe.get_all("LMS Learning Path Assignment", fields=["name", "learning_path", "duration", "creation", "is_mandatory"])
            for a in assignments_p: assignment_map[a.learning_path] = a
        
        all_module_categories = frappe.get_all("LMS Module Category", fields=["parent", "category"])
        module_categories_map = {}
        for mc in all_module_categories:
            if mc.parent not in module_categories_map:
                module_categories_map[mc.parent] = set()
            module_categories_map[mc.parent].add(mc.category)
        
        # Filter learners based on user_filter
        learner_filters = {"role": "LMS-Learner"}
        if user_filter is None:
            pass # no extra filter
        else:
            learner_filters["parent"] = ["in", user_filter]
            
        all_learner_roles = frappe.get_all("Has Role", filters=learner_filters, fields=["parent", "creation"])
        
        quiz_submissions = frappe.get_all("LMS Quiz Submission", fields=["score", "submitted_on", "user"])

        def compute_metrics_for_date(dt):
            learners_by_dt = set([r.parent for r in all_learner_roles if getdate(r.creation) <= getdate(dt)])
            thirty_days_before_dt = add_days(dt, -30)
            
            tracker_filters = {"creation": ["<=", dt]}
            if user_filter is not None:
                tracker_filters["user"] = ["in", user_filter]
                
            trackers_dt = []
            if learning_type in ["all", "modules"]:
                mods = frappe.get_all("LMS Module Tracker", filters=tracker_filters, fields=["status", "modified", "module", "started_on", "creation", "completed_on", "user"])
                for m in mods:
                    m["item"] = m.module
                trackers_dt.extend(mods)
            if learning_type in ["all", "paths"]:
                paths = frappe.get_all("LMS Learning Path Tracker", filters=tracker_filters, fields=["status", "modified", "learning_path", "started_on", "creation", "completed_on", "user"])
                for p in paths:
                    p["item"] = p.learning_path
                trackers_dt.extend(paths)
            
            active_users_at_dt = set()
            for t in trackers_dt:
                if t.modified and getdate(thirty_days_before_dt) <= getdate(t.modified) <= getdate(dt):
                    if t.user in learners_by_dt:
                        active_users_at_dt.add(t.user)
            active_learners_val = len(active_users_at_dt)
            
            total_dt = len(trackers_dt)
            completed_dt = 0
            overdue_dt = 0
            
            completed_on_time_dt = 0
            completed_with_due_dt = 0
            attention_users = set()
            
            for t in trackers_dt:
                is_completed_by_dt = (t.status == "Completed" and (not t.completed_on or getdate(t.completed_on) <= getdate(dt)))
                if is_completed_by_dt:
                    completed_dt += 1
                
                if t.status == "Failed" and (not t.modified or getdate(t.modified) <= getdate(dt)):
                    if t.user in learners_by_dt:
                        attention_users.add(t.user)
                
                a = assignment_map.get(t.get("item"))
                if a and a.duration and t.started_on:
                    start_date = getdate(t.started_on)
                    due_date = add_days(start_date, a.duration)
                    if getdate(due_date) < getdate(dt) and not is_completed_by_dt:
                        overdue_dt += 1
                        if t.user in learners_by_dt:
                            attention_users.add(t.user)
                    
                    if is_completed_by_dt:
                        completed_with_due_dt += 1
                        if t.completed_on and getdate(t.completed_on) <= getdate(due_date):
                            completed_on_time_dt += 1
                            
            completion_rate_val = int((completed_dt / total_dt) * 100) if total_dt > 0 else 0
            overdue_assignments_val = overdue_dt
            
            compliance_modules = {mod for mod, cats in module_categories_map.items() if "Compliance" in cats}
            comp_trackers = [t for t in trackers_dt if t.get("item") in compliance_modules]
            comp_total = len(comp_trackers)
            comp_completed = len([t for t in comp_trackers if t.status == "Completed" and (not t.completed_on or getdate(t.completed_on) <= getdate(dt))])
            compliance_completion_val = int((comp_completed / comp_total) * 100) if comp_total > 0 else 0
            
            scores_dt = [s.score for s in quiz_submissions if s.submitted_on and getdate(s.submitted_on) <= getdate(dt) and s.user in learners_by_dt]
            assessment_score_val = int(sum(scores_dt) / len(scores_dt)) if len(scores_dt) > 0 else 0
            on_time_completion_val = int((completed_on_time_dt / completed_with_due_dt) * 100) if completed_with_due_dt > 0 else 0
            learners_needing_attention_val = len(attention_users)
            
            return active_learners_val, completion_rate_val, overdue_assignments_val, compliance_completion_val, assessment_score_val, on_time_completion_val, learners_needing_attention_val

        assessment_score_history = []
        on_time_completion_history = []
        learners_needing_attention_history = []

        for dt in intervals:
            if getdate(dt) > getdate(now()):
                active_learners_history.append(0)
                completion_rate_history.append(0)
                overdue_assignments_history.append(0)
                compliance_completion_history.append(0)
                assessment_score_history.append(0)
                on_time_completion_history.append(0)
                learners_needing_attention_history.append(0)
            else:
                a, c, o, cc, asc, otc, lna = compute_metrics_for_date(dt)
                active_learners_history.append(a)
                completion_rate_history.append(c)
                overdue_assignments_history.append(o)
                compliance_completion_history.append(cc)
                assessment_score_history.append(asc)
                on_time_completion_history.append(otc)
                learners_needing_attention_history.append(lna)
            
        dt_current = getdate(now())
        active_learners, completion_rate, overdue_assignments, compliance_completion, assessment_score, on_time_completion, learners_needing_attention = compute_metrics_for_date(dt_current)
        
        trend_label = "last month" if timeframe == "month" else "last year"
        dt_prev = add_months(dt_current, -1) if timeframe == "month" else add_months(dt_current, -12)
        a_prev, c_prev, o_prev, cc_prev, asc_prev, otc_prev, lna_prev = compute_metrics_for_date(dt_prev)
        
        def calc_trend(current, prev, is_percentage=True):
            if prev == 0:
                pct = 100 if current > 0 else 0
            else:
                pct = round(((current - prev) / prev) * 100)
            prefix = "+" if pct >= 0 else ""
            if is_percentage:
                return f"{prefix}{pct}% {trend_label}"
            else:
                diff = current - prev
                prefix = "+" if diff >= 0 else ""
                return f"{prefix}{diff} {trend_label}"
        
        a_trend = calc_trend(active_learners, a_prev)
        c_trend = f"vs {c_prev}% {trend_label}"
        o_trend = calc_trend(overdue_assignments, o_prev)
        cc_trend = calc_trend(compliance_completion, cc_prev)
        asc_trend = f"vs {asc_prev}% {trend_label}"
        otc_trend = f"vs {otc_prev}% {trend_label}"
        lna_trend = calc_trend(learners_needing_attention, lna_prev, is_percentage=False)
        
        return {
            "labels": [getdate(dt).strftime("%b") if timeframe == "year" else f"Week {i+1}" for i, dt in enumerate(intervals)],
            "activeLearners": active_learners,
            "activeLearnersTrend": a_trend,
            "activeLearnersHistory": active_learners_history,
            "completionRate": completion_rate,
            "completionRateTrend": c_trend,
            "completionRateHistory": completion_rate_history,
            "overdueAssignments": overdue_assignments,
            "overdueAssignmentsTrend": o_trend,
            "overdueAssignmentsHistory": overdue_assignments_history,
            "complianceCompletion": compliance_completion,
            "complianceCompletionTrend": cc_trend,
            "complianceCompletionHistory": compliance_completion_history,
            "assessmentScore": assessment_score,
            "assessmentScoreTrend": asc_trend,
            "assessmentScoreHistory": assessment_score_history,
            "onTimeCompletion": on_time_completion,
            "onTimeCompletionTrend": otc_trend,
            "onTimeCompletionHistory": on_time_completion_history,
            "learnersNeedingAttention": learners_needing_attention,
            "learnersNeedingAttentionTrend": lna_trend,
            "learnersNeedingAttentionHistory": learners_needing_attention_history
        }

    return {
        "month": get_data("month"),
        "year": get_data("year")
    }

@frappe.whitelist(allow_guest=True)
def get_learning_content_summary():
    user_filter = _get_filter_for_user()
    if user_filter == []:
        return {"items": [], "total": 0}
        
    # Get all eligible learners based on scope
    learner_filters = {"role": "LMS-Learner"}
    if user_filter is not None:
        learner_filters["parent"] = ["in", user_filter]
        
    all_learner_roles = frappe.get_all("Has Role", filters=learner_filters, fields=["parent"])
    eligible_learners = list(set([r.parent for r in all_learner_roles]))
    total_learners = len(eligible_learners)

    if not eligible_learners:
        return {"items": [], "total": 0}
        
    # Get trackers for eligible learners
    trackers = frappe.get_all("LMS Module Tracker", filters={"user": ["in", eligible_learners]}, fields=["name", "status", "module", "started_on", "creation", "user"])
    
    assignments = frappe.get_all("LMS Module Assignment", fields=["module", "duration"])
    assignment_map = {a.module: a for a in assignments}
    
    trackers_by_user = {u: [] for u in eligible_learners}
    for t in trackers:
        if t.user in trackers_by_user:
            trackers_by_user[t.user].append(t)
            
    status_counts = {
        "Passed": 0,
        "Failed": 0,
        "Overdue": 0,
        "In Progress": 0,
        "Not Started": 0
    }
    
    today_dt = getdate(today())
    
    for user, user_trackers in trackers_by_user.items():
        if not user_trackers:
            status_counts["Not Started"] += 1
            continue
            
        has_failed = False
        has_overdue = False
        has_in_progress = False
        all_passed = True
        
        for t in user_trackers:
            if t.status == "Failed":
                has_failed = True
                all_passed = False
            elif t.status == "Completed":
                score = frappe.db.get_value("LMS Quiz Submission", {"user": t.user, "enrollment": t.name}, "score")
                passing_score = frappe.db.get_value("LMS Module", t.module, "certificate_passing_percentage") or 60
                if score is not None and score < passing_score:
                    has_failed = True
                    all_passed = False
            else:
                all_passed = False
                is_overdue = False
                if t.started_on:
                    a = assignment_map.get(t.module)
                    if a and a.duration:
                        due = add_days(getdate(t.started_on), a.duration)
                        if getdate(due) < today_dt:
                            is_overdue = True

                if is_overdue:
                    has_overdue = True
                elif t.status == "In Progress":
                    has_in_progress = True
                    
        # Hierarchy of statuses: Overdue > Failed > In Progress > Not Started > Passed
        if has_overdue:
            status_counts["Overdue"] += 1
        elif has_failed:
            status_counts["Failed"] += 1
        elif has_in_progress:
            status_counts["In Progress"] += 1
        elif all_passed:
            status_counts["Passed"] += 1
        else:
            status_counts["Not Started"] += 1
            
    results = [{"name": k, "value": v} for k, v in status_counts.items()]
        
    return {
        "items": results,
        "total": total_learners,
    }

@frappe.whitelist(allow_guest=True)
def debug_correct_options(question_id):
    options = frappe.get_all("LMS Quiz Option", filters={"parent": question_id}, fields=["parent", "option_text", "is_correct"], ignore_permissions=True)
    return {"options": options}

@frappe.whitelist(allow_guest=True)
def get_assessment_performance(assessment_type="all"):
    user_filter = _get_filter_for_user()
    if user_filter == []:
        monthly_data = [{"month": calendar.month_abbr[month], "attempts": 0} for month in range(1, 13)]
        return {"averageScore": 0, "passRate": 0, "needsRetake": 0, "totalAttempts": 0, "retakeRate": 0, "monthlyAttempts": monthly_data}

    filters = {}
    if user_filter is not None:
        filters["user"] = ["in", user_filter]

    # All three tabs use the same source: LMS Quiz Submission
    submissions = frappe.get_all(
        "LMS Quiz Submission",
        filters=filters,
        fields=["passed", "score", "creation", "user", "quiz"],
        ignore_permissions=True
    )

    # Filter by quiz type if needed
    if assessment_type in ["quiz", "qa"]:
        quiz_names = list(set([s.quiz for s in submissions]))
        if quiz_names:
            quizzes = frappe.get_all("LMS Quiz", filters={"name": ["in", quiz_names]}, fields=["name", "quiz_type"])
            quiz_type_map = {q.name: q.quiz_type for q in quizzes}

            if assessment_type == "qa":
                submissions = [s for s in submissions if quiz_type_map.get(s.quiz) == "QA Assessment"]
            else:  # quiz
                submissions = [s for s in submissions if quiz_type_map.get(s.quiz) != "QA Assessment"]

    total_attempts = len(submissions)
    if total_attempts == 0:
        monthly_data = [{"month": calendar.month_abbr[month], "attempts": 0} for month in range(1, 13)]
        return {"averageScore": 0, "passRate": 0, "needsRetake": 0, "totalAttempts": 0, "retakeRate": 0, "monthlyAttempts": monthly_data}

    passed_submissions = [s for s in submissions if s.passed]
    total_passed = len(passed_submissions)
    total_failed = total_attempts - total_passed

    avg_score = sum([s.score or 0 for s in submissions]) / total_attempts
    pass_rate = int((total_passed / total_attempts) * 100)

    user_quiz_counts = {}
    for s in submissions:
        key = (s.user, s.quiz)
        user_quiz_counts[key] = user_quiz_counts.get(key, 0) + 1

    retakes = sum(1 for count in user_quiz_counts.values() if count > 1)
    retake_rate = int((retakes / len(user_quiz_counts)) * 100) if user_quiz_counts else 0

    current_year = getdate(today()).year
    monthly_attempts = defaultdict(int)
    for s in submissions:
        s_date = getdate(s.creation)
        if s_date.year == current_year:
            monthly_attempts[s_date.month] += 1

    monthly_data = [{"month": calendar.month_abbr[month], "attempts": monthly_attempts[month]} for month in range(1, 13)]

    return {
        "averageScore": int(avg_score),
        "passRate": pass_rate,
        "needsRetake": total_failed,
        "totalAttempts": total_attempts,
        "retakeRate": retake_rate,
        "monthlyAttempts": monthly_data
    }

@frappe.whitelist(allow_guest=True)
def get_department_performance():
    user = frappe.session.user
    roles = frappe.get_roles(user)
    
    # Check TL/Manager role first so it takes precedence over System Manager
    if "LMS-TL" in roles or "LMS Manager" in roles:
        lead_rows = frappe.get_all("LMS Team Lead", filters={"user": user, "parenttype": "LMS Team"}, fields=["parent"])
        team_names = list({r.parent for r in lead_rows})
        if not team_names:
            return []
        teams = frappe.get_all("LMS Team", filters={"name": ["in", team_names]}, fields=["name", "team_name"])
    elif "System Manager" in roles or "LMS Admin" in roles:
        teams = frappe.get_all("LMS Team", fields=["name", "team_name"])
    else:
        return []
    
    assignments = frappe.get_all("LMS Module Assignment", fields=["module", "duration"])
    assignment_map = {a.module: a for a in assignments}
    today_dt = getdate(today())
    
    results = []
    for t in teams:
        members = frappe.get_all("LMS Team Member", filters={"parent": t.name}, fields=["user"])
        member_emails = [m.user for m in members]
        
        if not member_emails:
            continue
            
        trackers = frappe.get_all("LMS Module Tracker", filters={"user": ["in", member_emails]}, fields=["user", "status", "total_score", "module", "started_on", "creation"])
        total_t = len(trackers)
        completed = len([tr for tr in trackers if tr.status == "Completed"])
        
        overdue_users = set()
        for tr in trackers:
            if tr.status != "Completed" and tr.started_on:
                a = assignment_map.get(tr.module)
                if a and a.duration:
                    due = getdate(add_days(getdate(tr.started_on), a.duration))
                    if due < today_dt:
                        overdue_users.add(tr.user)
        
        c_rate = int((completed / total_t) * 100) if total_t > 0 else 0
        
        completed_trackers = [tr for tr in trackers if tr.status == "Completed" and tr.total_score is not None]
        avg_score = sum([tr.total_score for tr in completed_trackers]) / len(completed_trackers) if len(completed_trackers) > 0 else 0
        
        results.append({
            "name": t.team_name,
            "completionRate": c_rate,
            "avgScore": int(avg_score),
            "overdueLearners": len(overdue_users),
            "criticalOverdue": len(overdue_users) > 5
        })
    return results


@frappe.whitelist(allow_guest=True)
def get_department_assessment_performance(assessment_type="all"):
    """
    Returns pass-rate per department based on LMS Quiz Submission data.
    assessment_type: "all" | "quiz" | "qa"
    """
    user = frappe.session.user
    roles = frappe.get_roles(user)

    # Check TL/Manager role first so it takes precedence over System Manager
    if "LMS-TL" in roles or "LMS Manager" in roles:
        lead_rows = frappe.get_all("LMS Team Lead", filters={"user": user, "parenttype": "LMS Team"}, fields=["parent"])
        team_names = list({r.parent for r in lead_rows})
        if not team_names:
            return []
        teams = frappe.get_all("LMS Team", filters={"name": ["in", team_names]}, fields=["name", "team_name"])
    elif "System Manager" in roles or "LMS Admin" in roles:
        teams = frappe.get_all("LMS Team", fields=["name", "team_name"])
    else:
        return []

    # Build quiz_type filter map
    quiz_type_filter = None
    if assessment_type == "quiz":
        quiz_type_filter = "Quiz"
    elif assessment_type == "qa":
        quiz_type_filter = "QA Assessment"

    results = []
    for t in teams:
        members = frappe.get_all("LMS Team Member", filters={"parent": t.name}, fields=["user"])
        member_emails = [m.user for m in members]

        if not member_emails:
            continue

        # Fetch submissions for these users
        sub_filters = {"user": ["in", member_emails]}
        submissions = frappe.get_all(
            "LMS Quiz Submission",
            filters=sub_filters,
            fields=["quiz", "passed", "user"],
            ignore_permissions=True
        )

        # Filter by quiz_type if needed
        if quiz_type_filter and submissions:
            quiz_names = list(set([s.quiz for s in submissions]))
            quizzes = frappe.get_all(
                "LMS Quiz",
                filters={"name": ["in", quiz_names]},
                fields=["name", "quiz_type"],
                ignore_permissions=True
            )
            valid_quiz_names = set(q.name for q in quizzes if q.quiz_type == quiz_type_filter)
            submissions = [s for s in submissions if s.quiz in valid_quiz_names]

        total = len(submissions)
        if total == 0:
            # Include dept with 0% so it still shows in the bar chart
            results.append({
                "name": t.team_name,
                "completionRate": 0,
                "avgScore": 0,
                "overdueLearners": 0,
                "criticalOverdue": False
            })
            continue

        passed = len([s for s in submissions if s.passed])
        pass_rate = int((passed / total) * 100)

        results.append({
            "name": t.team_name,
            "completionRate": pass_rate,   # reuse completionRate field so the component works unchanged
            "avgScore": 0,
            "overdueLearners": 0,
            "criticalOverdue": False
        })

    return results


@frappe.whitelist(allow_guest=True)
def get_recently_assigned_learning(learning_type="all"):
    user_filter = _get_filter_for_user()
    if user_filter == []:
        return []
        
    learner_filters = {"role": "LMS-Learner"}
    if user_filter is not None:
        learner_filters["parent"] = ["in", user_filter]
        
    all_learner_roles = frappe.get_all("Has Role", filters=learner_filters, fields=["parent"])
    eligible_learners = list(set([r.parent for r in all_learner_roles]))
    
    if not eligible_learners:
        return []

    results = []
    
    if learning_type in ["all", "modules"]:
        recent_trackers = frappe.get_all(
            "LMS Module Tracker",
            filters={"user": ["in", eligible_learners]},
            fields=["module", "creation"],
            order_by="creation desc",
            limit=100
        )
        recent_modules = []
        seen = set()
        for t in recent_trackers:
            if t.module not in seen:
                seen.add(t.module)
                recent_modules.append(t.module)
                if len(recent_modules) >= 5:
                    break
                    
        if recent_modules:
            modules = frappe.get_all("LMS Module", filters={"name": ["in", recent_modules]}, fields=["name", "module_name"])
            module_map = {m.name: m.module_name for m in modules}
            
            all_module_categories = frappe.get_all("LMS Module Category", fields=["parent", "category"])
            module_categories_map = {}
            for mc in all_module_categories:
                if mc.parent not in module_categories_map:
                    module_categories_map[mc.parent] = set()
                module_categories_map[mc.parent].add(mc.category)
                
            trackers = frappe.get_all(
                "LMS Module Tracker",
                filters={"module": ["in", recent_modules], "user": ["in", eligible_learners]},
                fields=["module", "status", "user"]
            )
            
            for mod in recent_modules:
                mod_trackers = [t for t in trackers if t.module == mod]
                assigned = len(mod_trackers)
                if assigned == 0: continue
                in_progress = len([t for t in mod_trackers if t.status == "In Progress"])
                completed = len([t for t in mod_trackers if t.status == "Completed"])
                c_rate = int((completed / assigned) * 100) if assigned > 0 else 0
                cats = list(module_categories_map.get(mod, []))
                cat_str = cats[0] if cats else "General"
                results.append({
                    "id": mod, "name": module_map.get(mod, mod), "type": "Module",
                    "category": cat_str, "assignedLearners": assigned, "inProgress": in_progress,
                    "completed": completed, "completionRate": c_rate
                })

    if learning_type in ["all", "paths"]:
        recent_trackers = frappe.get_all(
            "LMS Learning Path Tracker",
            filters={"user": ["in", eligible_learners]},
            fields=["learning_path", "creation"],
            order_by="creation desc",
            limit=100
        )
        recent_paths = []
        seen = set()
        for t in recent_trackers:
            if t.learning_path not in seen:
                seen.add(t.learning_path)
                recent_paths.append(t.learning_path)
                if len(recent_paths) >= 5:
                    break
                    
        if recent_paths:
            paths = frappe.get_all("LMS Learning Path", filters={"name": ["in", recent_paths]}, fields=["name", "path_name as module_name"])
            path_map = {p.name: p.module_name for p in paths}
            
            trackers = frappe.get_all(
                "LMS Learning Path Tracker",
                filters={"learning_path": ["in", recent_paths], "user": ["in", eligible_learners]},
                fields=["learning_path", "status", "user"]
            )
            
            for p in recent_paths:
                p_trackers = [t for t in trackers if t.learning_path == p]
                assigned = len(p_trackers)
                if assigned == 0: continue
                in_progress = len([t for t in p_trackers if t.status == "In Progress"])
                completed = len([t for t in p_trackers if t.status == "Completed"])
                c_rate = int((completed / assigned) * 100) if assigned > 0 else 0
                results.append({
                    "id": p, "name": path_map.get(p, p), "type": "Learning Path",
                    "category": "Path", "assignedLearners": assigned, "inProgress": in_progress,
                    "completed": completed, "completionRate": c_rate
                })

    return results

@frappe.whitelist(allow_guest=True)
def get_module_details_analytics(module_id, learning_type="module"):
    user_filter = _get_filter_for_user()
    if user_filter == []:
        return {}
        
    learner_filters = {"role": "LMS-Learner"}
    if user_filter is not None:
        learner_filters["parent"] = ["in", user_filter]
        
    all_learner_roles = frappe.get_all("Has Role", filters=learner_filters, fields=["parent"])
    eligible_learners = list(set([r.parent for r in all_learner_roles]))
    
    if not eligible_learners:
        return {}

    # Get module details
    try:
        if learning_type == "path":
            mod_doc = frappe.get_doc("LMS Learning Path", module_id)
            mod_name = mod_doc.path_name
        else:
            mod_doc = frappe.get_doc("LMS Module", module_id)
            mod_name = mod_doc.module_name
    except frappe.DoesNotExistError:
        return {}
        
    category_docs = frappe.get_all("LMS Module Category", filters={"parent": module_id}, fields=["category"]) if learning_type != "path" else []
    cat_str = category_docs[0].category if category_docs else "General"

    # Get trackers for eligible learners
    if learning_type == "path":
        trackers = frappe.get_all(
            "LMS Learning Path Tracker",
            filters={
                "learning_path": module_id,
                "user": ["in", eligible_learners]
            },
            fields=["name", "user", "status", "progress_percentage", "creation"]
        )
    else:
        trackers = frappe.get_all(
            "LMS Module Tracker",
            filters={
                "module": module_id,
                "user": ["in", eligible_learners]
            },
            fields=["name", "user", "status", "progress_percentage", "creation"]
        )
    
    total_learners = len(trackers)
    if total_learners == 0:
        return {
            "moduleName": mod_name,
            "category": cat_str,
            "type": "Learning Path" if learning_type == "path" else "Module",
            "overview": {"totalLearners": 0, "pass": 0, "inProgress": 0, "notStarted": 0, "overdue": 0},
            "departmentBreakdown": [],
            "topLearners": []
        }
        
    # User info and teams
    users = frappe.get_all("User", filters={"name": ["in", [t.user for t in trackers]]}, fields=["name", "full_name", "email"])
    user_map = {u.name: u for u in users}
    
    team_members = frappe.get_all("LMS Team Member", filters={"user": ["in", [t.user for t in trackers]]}, fields=["user", "parent"])
    user_team_map = {}
    for tm in team_members:
        if tm.user not in user_team_map:
            user_team_map[tm.user] = []
        user_team_map[tm.user].append(tm.parent)
        
    teams = frappe.get_all("LMS Team", fields=["name", "team_name"])
    team_name_map = {t.name: t.team_name for t in teams}

    passed = 0
    in_progress = 0
    not_started = 0
    overdue = 0
    
    duration = mod_doc.duration or 0
    now_ts = frappe.utils.now_datetime()
    
    dept_data = {}
    top_learners = []
    
    for t in trackers:
        # Check overdue
        is_overdue = False
        if duration > 0 and t.status != "Completed":
            created_dt = frappe.utils.get_datetime(t.creation)
            due_dt = frappe.utils.add_days(created_dt, duration)
            if due_dt < now_ts:
                is_overdue = True
                
        if t.status == "Completed":
            passed += 1
        elif is_overdue:
            overdue += 1
        elif t.status == "In Progress":
            in_progress += 1
        else:
            not_started += 1
            
        u_info = user_map.get(t.user)
        u_teams = user_team_map.get(t.user, [])
        primary_team_id = u_teams[0] if u_teams else None
        primary_team_name = team_name_map.get(primary_team_id, "No Department")
        
        # Dept breakdown
        if primary_team_name not in dept_data:
            dept_data[primary_team_name] = {"assigned": 0, "completed": 0}
        dept_data[primary_team_name]["assigned"] += 1
        if t.status == "Completed":
            dept_data[primary_team_name]["completed"] += 1
            
        # Top learners
        top_learners.append({
            "name": u_info.full_name if u_info else t.user,
            "email": u_info.email if u_info else t.user,
            "department": primary_team_name,
            "status": "Completed" if t.status == "Completed" else "In Progress" if t.status == "In Progress" else "Not Started",
            "completionRate": int(t.progress_percentage or 0)
        })
        
    dept_breakdown = []
    for dept, data in dept_data.items():
        c_rate = int((data["completed"] / data["assigned"]) * 100) if data["assigned"] > 0 else 0
        dept_breakdown.append({
            "department": dept,
            "assigned": data["assigned"],
            "completed": data["completed"],
            "completionRate": c_rate
        })
        
    top_learners = sorted(top_learners, key=lambda x: x["completionRate"], reverse=True)[:50]

    return {
        "moduleName": mod_name,
        "category": cat_str,
        "type": "Learning Path" if learning_type == "path" else "Module",
        "overview": {
            "totalLearners": total_learners,
            "pass": int((passed / total_learners) * 100),
            "inProgress": int((in_progress / total_learners) * 100),
            "notStarted": int((not_started / total_learners) * 100),
            "overdue": int((overdue / total_learners) * 100)
        },
        "departmentBreakdown": dept_breakdown,
        "topLearners": top_learners
    }

@frappe.whitelist(allow_guest=True)
def get_assessment_performance_list(assessment_type="all"):
    user_filter = _get_filter_for_user()
    if user_filter == []:
        return []
        
    filters = {}
    if user_filter is not None:
        filters["user"] = ["in", user_filter]

    submissions = frappe.get_all("LMS Quiz Submission", filters=filters, fields=["name", "user", "quiz", "score", "passed", "creation", "enrollment"], ignore_permissions=True)
    
    if not submissions:
        return []
        
    quiz_names = list(set([s.quiz for s in submissions]))
    quizzes = frappe.get_all("LMS Quiz", filters={"name": ["in", quiz_names]}, fields=["name", "title", "total_score", "passing_percentage", "max_attempts", "quiz_type"], ignore_permissions=True)
    quiz_map = {q.name: q for q in quizzes}
    
    if assessment_type == "qa":
        submissions = [s for s in submissions if quiz_map.get(s.quiz) and quiz_map[s.quiz].quiz_type == "QA Assessment"]
    elif assessment_type == "quiz":
        submissions = [s for s in submissions if quiz_map.get(s.quiz) and quiz_map[s.quiz].quiz_type == "Quiz"]
        
    if not submissions:
        return []
    
    tracker_names = list(set([s.enrollment for s in submissions if s.enrollment]))
    trackers = frappe.get_all("LMS Module Tracker", filters={"name": ["in", tracker_names]}, fields=["name", "module"], ignore_permissions=True)
    tracker_map = {t.name: t.module for t in trackers}
    
    module_names = list(set([t.module for t in trackers]))
    modules = frappe.get_all("LMS Module", filters={"name": ["in", module_names]}, fields=["name", "module_name"], ignore_permissions=True)
    module_map = {m.name: m.module_name for m in modules}
    
    users = frappe.get_all("User", filters={"name": ["in", [s.user for s in submissions]]}, fields=["name", "full_name", "email"], ignore_permissions=True)
    user_map = {u.name: u for u in users}

    user_quiz_attempts = {}
    for s in submissions:
        key = (s.user, s.quiz)
        user_quiz_attempts[key] = user_quiz_attempts.get(key, 0) + 1

    submissions.sort(key=lambda x: frappe.utils.get_datetime(x.creation), reverse=True)
    latest_submissions = {}
    for s in submissions:
        key = (s.user, s.quiz)
        if key not in latest_submissions:
            latest_submissions[key] = s
            
    results = []
    for (user, quiz_id), s in latest_submissions.items():
        q_doc = quiz_map.get(quiz_id)
        if not q_doc:
            continue
            
        # Filter by assessment type
        if assessment_type == "qa" and q_doc.quiz_type != "QA Assessment":
            continue
        if assessment_type == "quiz" and q_doc.quiz_type != "Quiz":
            continue
            
        u_info = user_map.get(user)
        mod_name = module_map.get(tracker_map.get(s.enrollment)) if s.enrollment else "Unknown Module"
        
        attempts_used = user_quiz_attempts.get((user, quiz_id), 1)
        max_attempts = q_doc.max_attempts or 0
        attempts_str = f"{attempts_used}/{max_attempts} used" if max_attempts > 0 else f"{attempts_used} used"
        
        results.append({
            "submissionId": s.name,
            "learnerName": u_info.full_name if u_info else user,
            "learnerEmail": u_info.email if u_info else user,
            "assessmentName": q_doc.title or quiz_id,
            "moduleName": mod_name,
            "type": q_doc.quiz_type or "Quiz",
            "score": f"{int(s.score or 0)}/{int(q_doc.total_score or 100)}",
            "passScore": int(q_doc.passing_percentage or 0),
            "attempts": attempts_str,
            "status": "Pass" if s.passed else "Failed"
        })
        
    return results

@frappe.whitelist(allow_guest=True)
def get_assessment_details(submission_id):
    user_filter = _get_filter_for_user()
    if user_filter == []:
        return None

    submissions = frappe.get_all("LMS Quiz Submission", filters={"name": submission_id}, fields=["name", "user", "quiz", "score", "passed", "time_taken", "submitted_on", "evaluation_feedback", "enrollment"], ignore_permissions=True)
    if not submissions:
        return None
    sub = submissions[0]

    if user_filter is not None and sub.user not in user_filter:
        return None

    users = frappe.get_all("User", filters={"name": sub.user}, fields=["full_name", "email"], ignore_permissions=True)
    u_info = users[0] if users else None

    team_members = frappe.get_all("LMS Team Member", filters={"user": sub.user}, fields=["parent"])
    department = "No Department"
    if team_members:
        teams = frappe.get_all("LMS Team", filters={"name": team_members[0].parent}, fields=["team_name"])
        if teams:
            department = teams[0].team_name

    quizzes = frappe.get_all("LMS Quiz", filters={"name": sub.quiz}, fields=["title", "total_score", "time_limit_mins", "passing_percentage"], ignore_permissions=True)
    quiz = quizzes[0] if quizzes else None

    module_name = ""
    if sub.enrollment:
        trackers = frappe.get_all("LMS Module Tracker", filters={"name": sub.enrollment}, fields=["module"], ignore_permissions=True)
        if trackers:
            modules = frappe.get_all("LMS Module", filters={"name": trackers[0].module}, fields=["module_name"], ignore_permissions=True)
            if modules:
                module_name = modules[0].module_name

    responses = frappe.get_all("LMS Quiz Response", filters={"parent": submission_id}, fields=["question", "selected_option", "is_correct", "evaluation_data", "manual_score"], ignore_permissions=True)
    
    question_ids = [str(r.question) for r in responses if r.question]
    q_map = {}
    if question_ids:
        questions = frappe.get_all("LMS Quiz Question", filters={"name": ["in", question_ids]}, fields=["name", "question_text", "score", "question_type"], ignore_permissions=True)
        q_map = {str(q.name): q for q in questions}

    correct_options = {}
    q_options_map = {}
    if question_ids:
        options = frappe.get_all("LMS Quiz Option", filters={"parent": ["in", question_ids]}, fields=["parent", "option_text", "is_correct", "score"], ignore_permissions=True)
        for opt in options:
            parent_id = str(opt.parent)
            if opt.is_correct:
                if parent_id in correct_options:
                    correct_options[parent_id] += " / " + opt.option_text
                else:
                    correct_options[parent_id] = opt.option_text
                    
            if parent_id not in q_options_map:
                q_options_map[parent_id] = []
            q_options_map[parent_id].append(opt)
            
    responses_data = []
    correct_count = 0
    incorrect_count = 0

    for r in responses:
        q_info = q_map.get(str(r.question))
        if not q_info:
            continue
            
        q_opts = q_options_map.get(str(r.question), [])
        requires_manual = (
            q_info.question_type == "Scenario Based" or
            (q_info.question_type == "Fill in the Blank" and len(q_opts) == 0)
        )
        
        if requires_manual:
            criteria_sum = sum(float(opt.score or 0) for opt in q_opts) if q_opts else 0
            q_max_score = criteria_sum if criteria_sum > 0 else float(q_info.score or 1)
            q_actual_score = float(r.manual_score or 0)
        else:
            q_max_score = 1
            q_actual_score = 1 if r.is_correct else 0
            
        if not requires_manual:
            if r.is_correct:
                correct_count += 1
            else:
                incorrect_count += 1
            
        import json
        feedback_str = ""
        if r.evaluation_data:
            try:
                eval_data = json.loads(r.evaluation_data)
                if isinstance(eval_data, dict):
                    feedback_str = eval_data.get("feedback", "")
            except:
                feedback_str = str(r.evaluation_data)

        responses_data.append({
            "questionText": frappe.utils.strip_html(q_info.question_text) if q_info.question_text else "",
            "questionType": q_info.question_type,
            "learnerAnswer": r.selected_option or "No Answer",
            "isCorrect": bool(r.is_correct),
            "correctAnswer": correct_options.get(str(r.question), ""),
            "score": q_actual_score,
            "maxScore": q_max_score,
            "feedback": feedback_str
        })

    time_taken_sec = int(sub.time_taken or 0)
    mins, secs = divmod(time_taken_sec, 60)
    time_taken_str = f"{mins} min {secs:02d} sec"
    if quiz and quiz.time_limit_mins:
        time_taken_str += f" / {quiz.time_limit_mins} mins"

    computed_max_score = sum(r["maxScore"] for r in responses_data)
    actual_score = sum(r["score"] for r in responses_data)
    
    total_questions = len(responses_data)
    attended_questions = sum(1 for r in responses_data if r.get("learnerAnswer") and r.get("learnerAnswer") != "No Answer")

    # Trust the submission's saved percentage score directly
    overall_score = int(sub.score or 0)

    taken_on = frappe.utils.formatdate(sub.submitted_on, "MMM dd, yyyy") if sub.submitted_on else ""

    # Fetch attempt history
    all_submissions = frappe.get_all("LMS Quiz Submission", filters={"user": sub.user, "quiz": sub.quiz}, fields=["name", "creation", "score", "passed"], order_by="creation asc", ignore_permissions=True)
    history = []
    for idx, s in enumerate(all_submissions):
        history.append({
            "submissionId": s.name,
            "attemptNumber": idx + 1,
            "date": frappe.utils.format_datetime(s.creation, "MMM dd, yyyy h:mm a") if s.creation else "",
            "score": int(s.score or 0),
            "passed": bool(s.passed)
        })

    return {
        "assessmentTitle": quiz.title if quiz else sub.quiz,
        "moduleName": module_name,
        "learner": {
            "name": u_info.full_name if u_info else sub.user,
            "email": u_info.email if u_info else sub.user,
            "designation": u_info.get("designation", "") if u_info else "",
            "department": department
        },
        "takenOn": f"Taken On: {taken_on}" if taken_on else "",
        "overallScore": f"{overall_score}%",
        "passed": bool(sub.passed),
        "completedPoints": f"{attended_questions} / {total_questions}",
        "timeTaken": time_taken_str,
        "overallFeedback": sub.evaluation_feedback or "",
        "summary": f"{correct_count} correct · {incorrect_count} incorrect",
        "responses": responses_data,
        "history": history
    }

@frappe.whitelist(allow_guest=True)
def debug_all_submissions():
    return frappe.get_all("LMS Quiz Submission", fields=["name", "quiz", "score", "time_taken"], limit=5, order_by="creation desc", ignore_permissions=True)

@frappe.whitelist(allow_guest=True)
def debug_submission(sub_id):
    sub = frappe.get_all("LMS Quiz Submission", filters={"name": sub_id}, fields=["*"], ignore_permissions=True)
    resp = frappe.get_all("LMS Quiz Response", filters={"parent": sub_id}, fields=["*"], ignore_permissions=True)
    return {"submission": sub, "responses": resp}

@frappe.whitelist(allow_guest=True)
def get_learner_metrics():
    user_filter = _get_filter_for_user()
    if user_filter == []:
        return {
            "totalAttempts": 0,
            "averageScore": 0,
            "passRate": 0,
            "failedAttempts": 0
        }
        
    filters = {}
    if user_filter:
        filters["user"] = ["in", user_filter]
        
    submissions = frappe.get_all("LMS Quiz Submission", filters=filters, fields=["passed", "score", "quiz"])
    total_attempts = len(submissions)
    passed_count = len([s for s in submissions if s.passed])
    failed_attempts = total_attempts - passed_count
    pass_rate = int((passed_count / total_attempts) * 100) if total_attempts > 0 else 0
    
    quiz_names = list(set([s.quiz for s in submissions if s.quiz]))
    quiz_totals = {}
    if quiz_names:
        quizzes = frappe.get_all("LMS Quiz", filters={"name": ["in", quiz_names]}, fields=["name", "total_score"])
        quiz_totals = {q.name: q.total_score for q in quizzes}
        
    total_percentage = 0
    scored_attempts = 0
    for s in submissions:
        if s.quiz and quiz_totals.get(s.quiz):
            total = quiz_totals.get(s.quiz)
            if total > 0:
                perc = ((s.score or 0) / total) * 100
                total_percentage += perc
                scored_attempts += 1
                
    average_score = int(total_percentage / scored_attempts) if scored_attempts > 0 else 0
    
    return {
        "totalAttempts": total_attempts,
        "averageScore": average_score,
        "passRate": pass_rate,
        "failedAttempts": failed_attempts
    }

@frappe.whitelist(allow_guest=True)
def get_learning_performance_list():
    user_filter = _get_filter_for_user()
    if user_filter == []:
        return []
        
    user_filters = {}
    if user_filter:
        user_filters["name"] = ["in", user_filter]
        
    users = frappe.get_all("User", filters=user_filters, fields=["name", "full_name", "email", "enabled"])
    if not users:
        return []
        
    user_emails = [u.email or u.name for u in users]
    
    # We don't query assignment status by user since assignment doesn't have a user field
    assignments = frappe.get_all("LMS Module Assignment", fields=["module", "duration"])
    assignment_map = {a.module: a for a in assignments}
    
    trackers = frappe.get_all("LMS Module Tracker", filters={"user": ["in", user_emails]}, fields=["user", "status", "progress_percentage", "module", "started_on"])
    try:
        employees = frappe.get_all("Employee", filters={"user_id": ["in", user_emails]}, fields=["user_id", "designation"])
        emp_map = {e.user_id: e.designation for e in employees}
    except:
        emp_map = {}
        
    team_members = frappe.get_all("LMS Team Member", filters={"user": ["in", user_emails]}, fields=["user", "parent"])
    user_team_map = {tm.user: tm.parent for tm in team_members}
    team_names = list(set(user_team_map.values()))
    teams = frappe.get_all("LMS Team", filters={"name": ["in", team_names]}, fields=["name", "team_name"])
    team_map = {t.name: t.team_name for t in teams}
    
    user_trackers = defaultdict(list)
    for t in trackers:
        user_trackers[t.user].append(t)
        
    results = []
    today_dt = getdate(today())
    
    for u in users:
        email = u.email or u.name
        
        team_id = user_team_map.get(email)
        dept_name = team_map.get(team_id) if team_id else "No Department"
        designation = emp_map.get(email) or "Learner"
        u_tracks = user_trackers.get(email, [])
        
        assigned_count = len(u_tracks)
        completed_count = len([t for t in u_tracks if t.status == "Completed"])
        
        total_prog = sum([t.progress_percentage or 0 for t in u_tracks])
        avg_progress = int(total_prog / len(u_tracks)) if u_tracks else 0
        
        progress_status = "On Track"
        has_overdue = False
        needs_attention = False
        
        for t in u_tracks:
            if t.status != "Completed" and t.started_on:
                a = assignment_map.get(t.module)
                if a and a.duration:
                    due = getdate(add_days(getdate(t.started_on), a.duration))
                    days_left = (due - today_dt).days
                    if days_left < 0:
                        has_overdue = True
                    elif days_left <= 3:
                        needs_attention = True
                    
        if has_overdue:
            progress_status = "Overdue"
        elif needs_attention:
            progress_status = "Needs Attention"
            
        results.append({
            "id": email,
            "learnerName": u.full_name or email,
            "email": email,
            "avatar": "",
            "department": dept_name,
            "designation": designation,
            "accountStatus": "Active" if u.enabled else "Inactive",
            "assignedLearning": f"{assigned_count} assigned · {completed_count} completed",
            "progress": avg_progress,
            "progressStatus": progress_status
        })
        
    return results

@frappe.whitelist(allow_guest=True)
def get_learner_details(learner_email):
    user_filter = _get_filter_for_user()
    if user_filter is not None and learner_email not in user_filter:
        return {}
        
    users = frappe.get_all("User", filters={"name": learner_email}, fields=["name", "full_name", "email", "enabled"])
    if not users:
        return {}
    u = users[0]
    
    try:
        employees = frappe.get_all("Employee", filters={"user_id": learner_email}, fields=["user_id", "designation"])
        designation = employees[0].designation if employees else "Learner"
    except:
        designation = "Learner"
        
    team_members = frappe.get_all("LMS Team Member", filters={"user": learner_email}, fields=["parent"])
    department = "No Department"
    if team_members:
        teams = frappe.get_all("LMS Team", filters={"name": team_members[0].parent}, fields=["team_name"])
        if teams:
            department = teams[0].team_name
            
    profile = {
        "name": u.full_name or u.email,
        "email": u.email,
        "avatar": "",
        "department": department,
        "designation": designation,
        "status": "Active" if u.enabled else "Inactive"
    }
    
    today_dt = getdate(today())
    
    mod_assignments = frappe.get_all("LMS Module Assignment", fields=["module", "duration"])
    mod_assign_map = {a.module: a for a in mod_assignments}
    
    mod_trackers = frappe.get_all("LMS Module Tracker", filters={"user": learner_email}, fields=["module", "status", "progress_percentage", "started_on"])
    mod_names = [t.module for t in mod_trackers]
    mod_titles = {}
    if mod_names:
        modules = frappe.get_all("LMS Module", filters={"name": ["in", mod_names]}, fields=["name", "module_name"])
        mod_titles = {m.name: m.module_name for m in modules}
    
    path_assignments = frappe.get_all("LMS Learning Path Assignment", fields=["learning_path", "duration"]) if frappe.db.exists("DocType", "LMS Learning Path Assignment") else []
    path_assign_map = {a.learning_path: a for a in path_assignments}
    
    path_trackers = frappe.get_all("LMS Learning Path Tracker", filters={"user": learner_email}, fields=["learning_path", "status", "progress_percentage", "started_on"]) if frappe.db.exists("DocType", "LMS Learning Path Tracker") else []
    path_names = [t.learning_path for t in path_trackers]
    path_titles = {}
    if path_names:
        paths = frappe.get_all("LMS Learning Path", filters={"name": ["in", path_names]}, fields=["name", "path_name"])
        path_titles = {p.name: p.path_name for p in paths}
        
    learnings = []
    
    for t in mod_trackers:
        l_status = t.status
        if t.status != "Completed" and t.started_on:
            l_status = "In Progress" if t.progress_percentage > 0 else "Not Started"
            a = mod_assign_map.get(t.module)
            if a and a.duration:
                due = getdate(add_days(getdate(t.started_on), a.duration))
                if (due - today_dt).days < 0:
                    l_status = "Overdue"
        elif t.status == "Completed":
            l_status = "Completed"
            
        learnings.append({
            "title": mod_titles.get(t.module, t.module),
            "type": "Module",
            "progress": int(t.progress_percentage or 0),
            "status": l_status
        })
        
    for t in path_trackers:
        l_status = t.status
        if t.status != "Completed" and t.started_on:
            l_status = "In Progress" if t.progress_percentage > 0 else "Not Started"
            a = path_assign_map.get(t.learning_path)
            if a and a.duration:
                due = getdate(add_days(getdate(t.started_on), a.duration))
                if (due - today_dt).days < 0:
                    l_status = "Overdue"
        elif t.status == "Completed":
            l_status = "Completed"
            
        learnings.append({
            "title": path_titles.get(t.learning_path, t.learning_path),
            "type": "Learning Path",
            "progress": int(t.progress_percentage or 0),
            "status": l_status
        })
        
    submissions = frappe.get_all("LMS Quiz Submission", filters={"user": learner_email}, fields=["quiz", "score", "passed"])
    quiz_names = [s.quiz for s in submissions]
    quiz_titles = {}
    quiz_totals = {}
    if quiz_names:
        quizzes = frappe.get_all("LMS Quiz", filters={"name": ["in", quiz_names]}, fields=["name", "title", "total_score"])
        for q in quizzes:
            quiz_titles[q.name] = q.title
            quiz_totals[q.name] = q.total_score
            
    assessments = []
    total_percentage = 0
    scored_attempts = 0
    
    for s in submissions:
        total = quiz_totals.get(s.quiz) or 0
        perc = int(((s.score or 0) / total) * 100) if total > 0 else 0
        if total > 0:
            total_percentage += perc
            scored_attempts += 1
            
        assessments.append({
            "title": quiz_titles.get(s.quiz, s.quiz),
            "type": "Assessment",
            "score": perc,
            "status": "Pass" if s.passed else "Failed"
        })
        
    attempts = len(submissions)
    average_score = int(total_percentage / scored_attempts) if scored_attempts > 0 else 0
    passed = len([s for s in submissions if s.passed])
    
    return {
        "profile": profile,
        "learnings": learnings,
        "assessments": assessments,
        "metrics": {
            "attempts": attempts,
            "averageScore": average_score,
            "passed": passed,
            "needsReview": 0
        }
    }


@frappe.whitelist(allow_guest=True)
def get_achievements_metrics():
    user_filter = _get_filter_for_user()
    if user_filter == []:
        return {
            "totalBadges": 0,
            "learnersRecognized": 0,
            "mostEarnedBadge": {"name": "-", "count": 0},
            "earnedThisMonth": {"count": 0, "change": 0}
        }
    
    # 1. Total active badges
    total_badges = frappe.db.count("LMS Badge", {"is_active": 1})
    
    # Base filter for Learner Badges
    lb_filters = {}
    if user_filter is not None:
        lb_filters["user"] = ["in", user_filter]
        
    # 2. Learners Recognized (distinct users)
    all_users = frappe.get_all("LMS Learner Badge", filters=lb_filters, fields=["user"])
    learners_recognized = len(set([x.user for x in all_users]))
    
    # 3. Most Earned Badge
    conditions = ""
    if user_filter is not None:
        format_strings = ','.join(['%s'] * len(user_filter))
        conditions = f"WHERE user IN ({format_strings})"
    
    query_vals = tuple(user_filter) if user_filter is not None else ()
    
    most_earned_query = f"""
        SELECT badge, COUNT(*) as count 
        FROM `tabLMS Learner Badge`
        {conditions}
        GROUP BY badge 
        ORDER BY count DESC 
        LIMIT 1
    """
    most_earned_res = frappe.db.sql(most_earned_query, query_vals, as_dict=True)
    
    most_earned_badge = {"name": "-", "count": 0}
    if most_earned_res:
        badge_doc = frappe.db.get_value("LMS Badge", most_earned_res[0].badge, "badge_name")
        most_earned_badge = {
            "name": badge_doc or most_earned_res[0].badge,
            "count": most_earned_res[0].count
        }
        
    # 4. Earned This Month vs Last Month
    from frappe.utils import today, get_first_day, add_months, get_last_day
    
    current_month_start = get_first_day(today())
    current_month_end = get_last_day(today())
    
    last_month_start = get_first_day(add_months(today(), -1))
    last_month_end = get_last_day(add_months(today(), -1))
    
    filters_cm = lb_filters.copy()
    filters_cm["awarded_on"] = ["between", [current_month_start, current_month_end]]
    
    filters_lm = lb_filters.copy()
    filters_lm["awarded_on"] = ["between", [last_month_start, last_month_end]]
    
    cm_count = frappe.db.count("LMS Learner Badge", filters_cm)
    lm_count = frappe.db.count("LMS Learner Badge", filters_lm)
    
    change = 0
    if lm_count > 0:
        change = int(((cm_count - lm_count) / lm_count) * 100)
    elif cm_count > 0:
        change = 100
        
    return {
        "totalBadges": total_badges,
        "learnersRecognized": learners_recognized,
        "mostEarnedBadge": most_earned_badge,
        "earnedThisMonth": {"count": cm_count, "change": change}
    }


@frappe.whitelist(allow_guest=True)
def get_achievements_performance():
    user_filter = _get_filter_for_user()
    if user_filter == []:
        return []
        
    # Get all active badges
    badges = frappe.get_all("LMS Badge", filters={"is_active": 1}, fields=["name", "badge_name", "badge_image", "description", "achievement_criteria"])
    
    # Get learner badges
    lb_filters = {}
    if user_filter is not None:
        lb_filters["user"] = ["in", user_filter]
        
    learner_badges = frappe.get_all("LMS Learner Badge", filters=lb_filters, fields=["badge", "user"])
    
    # We need top dept. We need user -> dept mapping.
    all_users = list(set([lb.user for lb in learner_badges]))
    
    user_team_map = defaultdict(list)
    if all_users:
        tms = frappe.get_all("LMS Team Member", filters={"user": ["in", all_users]}, fields=["user", "parent"])
        for tm in tms:
            user_team_map[tm.user].append(tm.parent)
            
    teams = frappe.get_all("LMS Team", fields=["name", "team_name"])
    team_name_map = {t.name: t.team_name for t in teams}
    
    # Aggregate data per badge
    badge_stats = defaultdict(lambda: {"count": 0, "depts": defaultdict(int)})
    
    for lb in learner_badges:
        badge_stats[lb.badge]["count"] += 1
        
        # Dept
        u_teams = user_team_map.get(lb.user, [])
        primary_team_id = u_teams[0] if u_teams else None
        primary_team_name = team_name_map.get(primary_team_id, "No Department")
        
        badge_stats[lb.badge]["depts"][primary_team_name] += 1
        
    results = []
    for b in badges:
        stats = badge_stats.get(b.name, {"count": 0, "depts": {}})
        
        # Calculate Top Dept
        top_dept = "No Department"
        top_dept_count = 0
        if stats["depts"]:
            sorted_depts = sorted(stats["depts"].items(), key=lambda x: x[1], reverse=True)
            top_dept = sorted_depts[0][0]
            top_dept_count = sorted_depts[0][1]
            
        results.append({
            "id": b.name,
            "badgeName": b.badge_name,
            "badgeImage": b.badge_image or "",
            "purpose": b.description or b.achievement_criteria or "",
            "learnersEarned": stats["count"],
            "topDept": f"{top_dept} ({top_dept_count})" if top_dept_count > 0 else "-"
        })
        
    # Sort by learnersEarned DESC
    results.sort(key=lambda x: x["learnersEarned"], reverse=True)
    return results


@frappe.whitelist(allow_guest=True)
def get_badge_details(badge_id):
    user_filter = _get_filter_for_user()
    
    # 1. Badge Info
    if not frappe.db.exists("LMS Badge", badge_id):
        return {}
        
    b = frappe.get_doc("LMS Badge", badge_id)
        
    badge_info = {
        "id": b.name,
        "badgeName": b.badge_name,
        "badgeImage": b.badge_image or "",
        "description": b.description or "",
        "achievementCriteria": b.achievement_criteria or "",
    }
    
    # 2. Impact Summary (Earned count)
    lb_filters = {"badge": badge_id}
    if user_filter is not None:
        if not user_filter:
            lb_filters["user"] = ["in", ["__empty__"]] # Force empty if Manager has no team
        else:
            lb_filters["user"] = ["in", user_filter]
        
    # All learner badges for this badge
    learner_badges = frappe.get_all("LMS Learner Badge", filters=lb_filters, fields=["user", "awarded_on"], order_by="awarded_on DESC")
    total_earned = len(learner_badges)
    badge_info["impactSummary"] = total_earned
    
    # 3. Department Achievement
    teams = frappe.get_all("LMS Team", fields=["name", "team_name"])
    team_name_map = {t.name: t.team_name for t in teams}
    
    # Find all team members within scope
    tm_filters = {}
    if user_filter is not None:
        if not user_filter:
            tm_filters["user"] = ["in", ["__empty__"]]
        else:
            tm_filters["user"] = ["in", user_filter]
        
    all_team_members = frappe.get_all("LMS Team Member", filters=tm_filters, fields=["user", "parent"])
    
    dept_targets = defaultdict(int)
    user_to_dept = {}
    
    for tm in all_team_members:
        dept_name = team_name_map.get(tm.parent, "No Department")
        dept_targets[dept_name] += 1
        if tm.user not in user_to_dept:
            user_to_dept[tm.user] = dept_name
            
    # If no team members were found, but there are earners (e.g. Admin view with users not in teams)
    # We should still show them in "No Department"
    dept_earned = defaultdict(int)
    earners_set = set([lb.user for lb in learner_badges])
    for u in earners_set:
        d_name = user_to_dept.get(u, "No Department")
        dept_earned[d_name] += 1
        
    department_achievement = []
    # Add departments that have targets or earned
    all_depts_to_show = set(list(dept_targets.keys()) + list(dept_earned.keys()))
    
    for d_name in all_depts_to_show:
        target = dept_targets.get(d_name, 0)
        earned = dept_earned.get(d_name, 0)
        if target > 0 or earned > 0:
            department_achievement.append({
                "department": d_name,
                "earned": earned,
                "target": max(target, earned) # Target shouldn't be less than earned in case of orphaned users
            })
            
    department_achievement.sort(key=lambda x: x["earned"], reverse=True)
    badge_info["departmentAchievement"] = department_achievement
    badge_info["departmentTotalEarned"] = sum([d["earned"] for d in department_achievement])
    
    # 4. Latest Achievements
    from frappe.utils import formatdate
    recent_lbs = learner_badges[:5]
    latest_achievements = []
    
    if recent_lbs:
        users = [r.user for r in recent_lbs]
        user_docs = frappe.get_all("User", filters={"name": ["in", users]}, fields=["name", "full_name", "user_image"])
        user_map = {u.name: u for u in user_docs}
        
        for lb in recent_lbs:
            u_info = user_map.get(lb.user)
            if u_info:
                latest_achievements.append({
                    "name": u_info.full_name or lb.user,
                    "avatar": u_info.user_image or "",
                    "department": user_to_dept.get(lb.user, "No Department"),
                    "date": formatdate(lb.awarded_on, "MMM dd, yyyy") if lb.awarded_on else ""
                })
                
    badge_info["latestAchievements"] = latest_achievements
    
    return badge_info
