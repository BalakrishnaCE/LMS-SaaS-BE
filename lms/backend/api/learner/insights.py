import frappe
from frappe.utils import today, add_days, getdate

@frappe.whitelist(allow_guest=True)
def get_upcoming_deadlines():
    assignments = frappe.get_all("LMS Module Assignment", fields=["name", "module", "duration", "is_mandatory"])
    assignment_map = {a.module: a for a in assignments}
    
    modules = frappe.get_all("LMS Module", fields=["name", "module_name"])
    module_name_map = {m.name: m.module_name for m in modules}
    
    approaching = {}
    today_dt = getdate(today())
    
    published_modules = frappe.get_all("LMS Module", filters={"status": "Published"}, pluck="name")
    
    trackers = []
    if published_modules:
        trackers = frappe.get_all("LMS Module Tracker", filters={"status": ["!=", "Completed"], "module": ["in", published_modules]}, fields=["module", "started_on"])
        
    for t in trackers:
        if not t.started_on:
            continue
        a = assignment_map.get(t.module)
        if a and a.duration:
            due = getdate(add_days(getdate(t.started_on), a.duration))
            days_left = frappe.utils.date_diff(due, today_dt)
            
            if days_left < 0:
                category = "Overdue"
            elif 0 <= days_left <= 7:
                category = "Approaching in 7 days"
            elif 7 < days_left <= 30:
                category = "Approaching in 30 days"
            else:
                continue
                
            key = (t.module, category)
            if key not in approaching:
                approaching[key] = {"count": 0, "mandatory": a.is_mandatory}
            approaching[key]["count"] += 1
                
    results = []
    # Sort order for categories: Overdue first, then 7 days, then 30 days
    category_weight = {"Overdue": 0, "Approaching in 7 days": 1, "Approaching in 30 days": 2}
    
    for key, data in approaching.items():
        module_id, category = key
        results.append({
            "id": f"{module_id}-{category}",
            "name": module_name_map.get(module_id, module_id),
            "type": "Module",
            "date": category,
            "pending": data['count'],
            "critical": bool(data['mandatory']) or category == "Overdue",
            "_weight": category_weight.get(category, 3)
        })
        
    results = sorted(results, key=lambda x: (x["_weight"], -x["pending"]))[:5]
    
    # Clean up internal sort key
    for r in results:
        r.pop("_weight", None)
        
    return results

@frappe.whitelist(allow_guest=True)
def get_recently_assigned():
    from frappe.utils import add_days, formatdate

    # Fetch recent Module and Learning Path assignments
    mod_assignments = frappe.get_all("LMS Module Assignment",
        fields=["name", "module as learning_id", "creation", "duration"],
        order_by="creation desc",
        limit=50
    )
    for a in mod_assignments:
        a["type"] = "Module"

    lp_assignments = frappe.get_all("LMS Learning Path Assignment",
        fields=["name", "learning_path as learning_id", "creation", "duration"],
        order_by="creation desc",
        limit=50
    )
    for a in lp_assignments:
        a["type"] = "Learning Path"

    all_assignments = mod_assignments + lp_assignments
    all_assignments.sort(key=lambda x: x.creation, reverse=True)

    seen = set()
    unique_assignments = []
    for a in all_assignments:
        key = (a["type"], a["learning_id"])
        if key not in seen:
            seen.add(key)
            unique_assignments.append(a)
        if len(unique_assignments) >= 30:
            break

    results = []
    for a in unique_assignments:
        if a["type"] == "Module":
            m_doc = frappe.db.get_value("LMS Module", a["learning_id"], ["module_name", "status"], as_dict=True)
            if not m_doc:
                continue
            title = m_doc.module_name or a["learning_id"]
            cats = frappe.get_all("LMS Module Category", filters={"parent": a["learning_id"]}, pluck="category", order_by="idx asc")
            cat = ", ".join(dict.fromkeys(c for c in cats if c)) if cats else "General"
            trackers = frappe.get_all("LMS Module Tracker", filters={"module": a["learning_id"], "status": ("!=", "Unassigned")}, fields=["status"])
            total_assigned = len(trackers)
            completed = len([t for t in trackers if t.status == "Completed"])
        else:
            p_doc = frappe.db.get_value("LMS Learning Path", a["learning_id"], ["path_name", "status"], as_dict=True)
            if not p_doc:
                continue
            title = p_doc.path_name or a["learning_id"]
            cats = frappe.get_all("LMS Module Category", filters={"parent": a["learning_id"]}, pluck="category", order_by="idx asc")
            cat = ", ".join(dict.fromkeys(c for c in cats if c)) if cats else "General"
            trackers = frappe.get_all("LMS Learning Path Tracker", filters={"learning_path": a["learning_id"], "status": ("!=", "Unassigned")}, fields=["status"])
            total_assigned = len(trackers)
            completed = len([t for t in trackers if t.status == "Completed"])

        progress = int((completed / total_assigned) * 100) if total_assigned > 0 else 0

        # Calculate Due Date
        due_date_str = "No Limit"
        if a.get("duration"):
            due_date = add_days(a["creation"], a["duration"])
            due_date_str = formatdate(due_date, "MMM d, yyyy")

        results.append({
            "id": a["name"],
            "moduleId": a["learning_id"],
            "title": title,
            "type": a["type"],
            "category": cat,
            "assignedLearners": total_assigned,
            "dueDate": due_date_str,
            "progress": progress
        })

    return results
