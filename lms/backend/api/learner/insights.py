import frappe
from frappe.utils import today, add_days, getdate

@frappe.whitelist(allow_guest=True)
def get_upcoming_deadlines():
    assignments = frappe.get_all("LMS Module Assignment", fields=["name", "module", "duration", "is_mandatory"])
    assignment_map = {a.module: a for a in assignments}
    
    approaching = {}
    today_dt = getdate(today())
    next_week = getdate(add_days(today_dt, 30))
    
    trackers = frappe.get_all("LMS Module Tracker", filters={"status": ["!=", "Completed"]}, fields=["module", "started_on"])
    for t in trackers:
        if not t.started_on:
            continue
        a = assignment_map.get(t.module)
        if a and a.duration:
            due = getdate(add_days(getdate(t.started_on), a.duration))
            if today_dt <= due <= next_week:
                if t.module not in approaching:
                    approaching[t.module] = {"count": 0, "mandatory": a.is_mandatory}
                approaching[t.module]["count"] += 1
                
    results = []
    for module_name, data in approaching.items():
        results.append({
            "id": module_name,
            "name": module_name,
            "type": "Module",
            "date": "Approaching in 30 days",
            "pending": data['count'],
            "critical": bool(data['mandatory'])
        })
        
    return sorted(results, key=lambda x: x["pending"], reverse=True)[:5]

@frappe.whitelist(allow_guest=True)
def get_recently_assigned():
    assignments = frappe.get_all("LMS Module Assignment", 
        fields=["name", "module", "creation", "duration"],
        limit=20,
        order_by="creation desc"
    )
    
    seen_modules = set()
    unique_assignments = []
    for a in assignments:
        if a.module not in seen_modules:
            seen_modules.add(a.module)
            unique_assignments.append(a)
        if len(unique_assignments) == 5:
            break
            
    results = []
    for a in unique_assignments:
        trackers = frappe.get_all("LMS Module Tracker", filters={"module": a.module}, fields=["status"])
        total_assigned = len(trackers)
        completed = len([t for t in trackers if t.status == "Completed"])
        progress = int((completed / total_assigned) * 100) if total_assigned > 0 else 0
        
        results.append({
            "id": a.name,
            "name": a.module,
            "assignedLearners": total_assigned,
            "dueDate": f"{a.duration} Days" if a.duration else "No Limit",
            "progress_percentage": progress,
            "actions": ["View Progress", "Send Reminder"]
        })
    return results
