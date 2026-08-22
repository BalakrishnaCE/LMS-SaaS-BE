import frappe
from frappe import _

@frappe.whitelist()
def get_learning_paths():
    """
    Returns aggregated statistics and a list of all Learning Paths.
    """
    paths = frappe.get_all(
        "LMS Learning Path",
        fields=["name", "path_name", "status", "description", "image", "is_sequential"]
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
