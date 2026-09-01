import frappe
import json


def _ensure_user(learner: dict) -> str:
    """
    Ensure a Frappe User exists for the given learner email.
    Creates the User, assigns LMS-Learner role, creates LMS User Settings,
    and adds them to the corresponding LMS Team (department) if needed.
    Returns the user email (which is the Frappe User name/PK).
    """
    email = learner.get("email", "").strip()
    if not email:
        return None

    if frappe.db.exists("User", email):
        return email

    # Parse name into first/last
    full_name = (learner.get("name") or "").strip()
    name_parts = full_name.split(" ", 1)
    first_name = name_parts[0] or email.split("@")[0]
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    # Create the user
    user = frappe.new_doc("User")
    user.email = email
    user.first_name = first_name
    user.last_name = last_name
    user.username = email.split("@")[0]
    user.send_welcome_email = 0
    user.enabled = 1
    user.new_password = frappe.generate_hash(length=12)  # random temp password
    user.append("roles", {"role": "LMS-Learner"})
    user.insert(ignore_permissions=True)

    # Create LMS User Settings
    designation = learner.get("designation", "")
    joining_date = learner.get("joiningDate") or learner.get("joining_date") or None
    if designation or joining_date:
        settings = frappe.new_doc("LMS User Settings")
        settings.system_user = email
        if designation:
            settings.designation = designation
        if joining_date:
            settings.joining_date = joining_date
        settings.insert(ignore_permissions=True)

    # Add to team matching the department
    department = (learner.get("department") or "").strip()
    if department:
        # Find or create the LMS Team for this department
        team_name = frappe.db.get_value("LMS Team", {"team_name": department}, "name")
        if not team_name:
            team = frappe.new_doc("LMS Team")
            team.team_name = department
            team.is_active = 1
            team.insert(ignore_permissions=True)
            team_name = team.name

        # Add user to team if not already there
        already_member = frappe.db.exists(
            "LMS Team Member", {"parent": team_name, "user": email}
        )
        if not already_member:
            team_doc = frappe.get_doc("LMS Team", team_name)
            team_doc.append("learners", {"user": email})
            team_doc.save(ignore_permissions=True)

    return email


@frappe.whitelist()
def save_import_assignment(groups_json):
    """
    Save assignment groups from the Import Learners flow.

    For each group, first ensures every learner exists as a Frappe User
    (creates them if missing), then for each module/learning_path assigned:
    - Creates or updates a LMS Module Assignment (Manual type)
    - Creates or updates a LMS Learning Path Assignment (Manual type)

    Args:
        groups_json: JSON list of assignment groups, each with:
            {
                id, label, mode,
                learners: [{email, name, department, designation, ...}],
                selectedContent: [{id, type: 'module'|'learning_path', title}]
            }
    """
    groups = json.loads(groups_json) if isinstance(groups_json, str) else groups_json

    created = {"module_assignments": [], "lp_assignments": [], "users_created": []}

    for group in groups:
        learners = group.get("learners", [])
        selected_content = group.get("selectedContent", [])

        if not learners or not selected_content:
            continue

        # Step 1: Ensure all learners exist as Frappe Users
        valid_emails = []
        for learner in learners:
            email = _ensure_user(learner)
            if email:
                valid_emails.append(email)
                if not frappe.db.exists("User", email) is False:
                    created["users_created"].append(email)

        if not valid_emails:
            continue

        modules = [c for c in selected_content if c.get("type") == "module"]
        learning_paths = [c for c in selected_content if c.get("type") == "learning_path"]

        # Step 2: Create/update LMS Module Assignments
        for module_item in modules:
            module_id = module_item.get("id")
            if not module_id:
                continue

            existing = frappe.db.get_value(
                "LMS Module Assignment",
                {"module": module_id, "assignment_type": "Manual"},
                "name"
            )

            if existing:
                doc = frappe.get_doc("LMS Module Assignment", existing)
                existing_emails = {row.user for row in doc.get("learners", [])}
                for email in valid_emails:
                    if email not in existing_emails:
                        doc.append("learners", {"user": email})
                doc.save(ignore_permissions=True)
                created["module_assignments"].append(existing)
            else:
                doc = frappe.new_doc("LMS Module Assignment")
                doc.module = module_id
                doc.assignment_type = "Manual"
                for email in valid_emails:
                    doc.append("learners", {"user": email})
                doc.insert(ignore_permissions=True)
                created["module_assignments"].append(doc.name)

        # Step 3: Create/update LMS Learning Path Assignments
        for lp_item in learning_paths:
            lp_id = lp_item.get("id")
            if not lp_id:
                continue

            existing = frappe.db.get_value(
                "LMS Learning Path Assignment",
                {"learning_path": lp_id, "assignment_type": "Manual"},
                "name"
            )

            if existing:
                doc = frappe.get_doc("LMS Learning Path Assignment", existing)
                existing_emails = {row.user for row in doc.get("learners", [])}
                for email in valid_emails:
                    if email not in existing_emails:
                        doc.append("learners", {"user": email})
                doc.save(ignore_permissions=True)
                created["lp_assignments"].append(existing)
            else:
                doc = frappe.new_doc("LMS Learning Path Assignment")
                doc.learning_path = lp_id
                doc.assignment_type = "Manual"
                for email in valid_emails:
                    doc.append("learners", {"user": email})
                doc.insert(ignore_permissions=True)
                created["lp_assignments"].append(doc.name)

    frappe.db.commit()
    return created
