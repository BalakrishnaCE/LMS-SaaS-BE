import frappe
import calendar
from frappe.utils import today, add_days, add_months, getdate, now


def _get_team_member_emails(tl_user):
    """
    Return email list of all members across teams where tl_user is a team lead.
    Uses the LMS Team Lead child table (parentfield='team_leads') which is
    managed directly by the Frappe Desk LMS Team form — so any add/remove in
    Frappe Desk is immediately reflected here without any extra sync step.
    """
    # All teams where this user is listed as a team lead
    lead_rows = frappe.get_all(
        "LMS Team Lead",
        filters={"user": tl_user, "parenttype": "LMS Team"},
        fields=["parent"],
    )
    team_names = list({r.parent for r in lead_rows})

    if not team_names:
        return []

    # Collect all learners from those teams
    member_emails = set()
    for team_name in team_names:
        members = frappe.get_all(
            "LMS Team Member",
            filters={"parent": team_name, "parenttype": "LMS Team"},
            fields=["user"],
        )
        for m in members:
            member_emails.add(m.user)

    return list(member_emails)


@frappe.whitelist()
def get_manager_metrics():
    tl_user = frappe.session.user
    member_emails = _get_team_member_emails(tl_user)

    assignments = frappe.get_all("LMS Module Assignment", fields=["name", "module", "duration", "is_mandatory"])
    assignment_map = {a.module: a for a in assignments}

    def get_data(timeframe):
        current_year = getdate(today()).year
        current_month = getdate(today()).month

        if timeframe == "year":
            intervals = [getdate(f"{current_year}-{m:02d}-28") for m in range(1, 13)]
        else:
            num_days = calendar.monthrange(current_year, current_month)[1]
            intervals = [
                getdate(f"{current_year}-{current_month:02d}-07"),
                getdate(f"{current_year}-{current_month:02d}-14"),
                getdate(f"{current_year}-{current_month:02d}-21"),
                getdate(f"{current_year}-{current_month:02d}-{num_days}"),
            ]

        active_learners_history = []
        pass_rate_history = []
        at_risk_history = []

        def compute_for_date(dt):
            """
            Mirrors admin dashboard logic — cumulative as-of-date snapshot,
            scoped to this TL's team members only.
            """
            filters = {"creation": ["<=", dt]}
            if member_emails:
                filters["user"] = ["in", member_emails]

            trackers = frappe.get_all(
                "LMS Module Tracker",
                filters=filters,
                fields=["user", "status", "module", "started_on", "modified", "completed_on"],
            )

            # Active: modified within 30 days before dt
            thirty_days_before = add_days(dt, -30)
            active_users = set(
                t.user for t in trackers
                if t.modified and getdate(thirty_days_before) <= getdate(t.modified) <= getdate(dt)
            )
            active_count = len(active_users)

            # Pass rate: completed by dt / total trackers created by dt
            total = len(trackers)
            completed = sum(
                1 for t in trackers
                if t.status == "Completed" and (not t.completed_on or getdate(t.completed_on) <= getdate(dt))
            )
            pass_rate = int((completed / total) * 100) if total > 0 else 0

            # At risk: not completed and overdue as of dt
            at_risk = set()
            for t in trackers:
                if t.status != "Completed" and t.started_on:
                    a = assignment_map.get(t.module)
                    if a and a.duration:
                        due = add_days(getdate(t.started_on), a.duration)
                        if getdate(due) < getdate(dt):
                            at_risk.add(t.user)

            return active_count, pass_rate, len(at_risk)

        for dt in intervals:
            a, p, r = compute_for_date(dt)
            active_learners_history.append(a)
            pass_rate_history.append(p)
            at_risk_history.append(r)

        # Current values from the last interval (same as admin)
        active_learners = active_learners_history[-1]
        pass_rate = pass_rate_history[-1]
        at_risk = at_risk_history[-1]

        # Trend: compare last interval vs same point 1 month / 1 year ago
        trend_label = "last month" if timeframe == "month" else "last year"
        dt_current = intervals[-1]
        dt_prev = add_months(dt_current, -1) if timeframe == "month" else add_months(dt_current, -12)
        a_prev, p_prev, r_prev = compute_for_date(dt_prev)

        a_pct = round(((active_learners - a_prev) / a_prev) * 100) if a_prev > 0 else (100 if active_learners > 0 else 0)
        a_trend = f"+{a_pct}% {trend_label}" if a_pct >= 0 else f"{a_pct}% {trend_label}"
        p_trend = f"vs {p_prev}% {trend_label}"
        r_pct = round(((at_risk - r_prev) / r_prev) * 100) if r_prev > 0 else (100 if at_risk > 0 else 0)
        r_trend = f"+{r_pct}% {trend_label}" if r_pct >= 0 else f"{r_pct}% {trend_label}"

        # TL's own pending learning (not time-bounded — current state)
        today_dt = getdate(today())
        tl_trackers = frappe.get_all(
            "LMS Module Tracker",
            filters={"user": tl_user, "status": ["!=", "Completed"]},
            fields=["module", "started_on"],
        )
        pending_count = len(tl_trackers)
        due_this_week = 0
        for t in tl_trackers:
            if t.started_on:
                a = assignment_map.get(t.module)
                if a and a.duration:
                    due = add_days(getdate(t.started_on), a.duration)
                    if today_dt <= getdate(due) <= add_days(today_dt, 7):
                        due_this_week += 1

        labels = [
            getdate(dt).strftime("%b") if timeframe == "year" else f"Week {i+1}"
            for i, dt in enumerate(intervals)
        ]

        return {
            "labels": labels,
            "activeLearners": active_learners,
            "activeLearnersTrend": a_trend,
            "activeLearnersHistory": active_learners_history,
            "passRate": pass_rate,
            "passRateTrend": p_trend,
            "passRateHistory": pass_rate_history,
            "atRiskLearners": at_risk,
            "atRiskTrend": r_trend,
            "atRiskHistory": at_risk_history,
            "myPendingCount": pending_count,
            "myDueThisWeek": due_this_week,
        }

    return {
        "month": get_data("month"),
        "year": get_data("year"),
    }

@frappe.whitelist()
def get_team_performance_overview(timeframe="7days"):
    tl_user = frappe.session.user
    member_emails = _get_team_member_emails(tl_user)

    if not member_emails:
        return []

    filters = {"user": ["in", member_emails]}
    today_dt = getdate(today())
    
    if timeframe == "7days":
        start_date = add_days(today_dt, -7)
        filters["modified"] = [">=", start_date]
    elif timeframe == "30days":
        start_date = add_days(today_dt, -30)
        filters["modified"] = [">=", start_date]
    elif timeframe == "month":
        start_date = getdate(f"{today_dt.year}-{today_dt.month:02d}-01")
        filters["modified"] = [">=", start_date]
    elif timeframe == "year":
        start_date = getdate(f"{today_dt.year}-01-01")
        filters["modified"] = [">=", start_date]

    trackers = frappe.get_all("LMS Module Tracker", filters=filters, fields=["status", "module", "started_on"])
    
    assignments = frappe.get_all("LMS Module Assignment", fields=["module", "duration"])
    assignment_map = {a.module: a for a in assignments}

    status_counts = {
        "Completed": 0,
        "Overdue": 0,
        "In Progress": 0,
        "Not Started": 0
    }

    for t in trackers:
        if t.status == "Completed":
            status_counts["Completed"] += 1
        else:
            is_overdue = False
            if t.started_on:
                a = assignment_map.get(t.module)
                if a and a.duration:
                    due = add_days(getdate(t.started_on), a.duration)
                    if getdate(due) < today_dt:
                        is_overdue = True

            if is_overdue:
                status_counts["Overdue"] += 1
            elif t.status == "In Progress":
                status_counts["In Progress"] += 1
            else:
                status_counts["Not Started"] += 1

    # Format the same way as LearningContentGauge (just raw values, gauge computes percentages)
    results = []
    for k, v in status_counts.items():
        if v > 0:
            results.append({
                "name": k,
                "value": v
            })

    return results
