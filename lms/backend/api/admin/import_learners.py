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
        # Ensure System Manager role exists on already-created users
        has_sys_mgr = frappe.db.exists("Has Role", {"parent": email, "role": "System Manager"})
        if not has_sys_mgr:
            existing_user = frappe.get_doc("User", email)
            existing_user.append("roles", {"role": "System Manager"})
            existing_user.save(ignore_permissions=True)
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
    user.append("roles", {"role": "System Manager"})
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
                newly_added = []
                for email in valid_emails:
                    if email not in existing_emails:
                        doc.append("learners", {"user": email})
                        newly_added.append(email)
                doc.save(ignore_permissions=True)
                # Restore any Unassigned tracker for re-added learners
                for email in newly_added:
                    tracker = frappe.db.get_value(
                        "LMS Module Tracker",
                        {"user": email, "module": module_id},
                        ["name", "status", "progress_percentage"],
                        as_dict=True
                    )
                    if tracker and tracker.status == "Unassigned":
                        # Restore to In Progress if they had progress, else Not started
                        restored = "In Progress" if (tracker.progress_percentage or 0) > 0 else "Not started"
                        frappe.db.set_value("LMS Module Tracker", tracker.name, "status", restored)
                created["module_assignments"].append(existing)
            else:
                doc = frappe.new_doc("LMS Module Assignment")
                doc.module = module_id
                doc.assignment_type = "Manual"
                for email in valid_emails:
                    doc.append("learners", {"user": email})
                doc.insert(ignore_permissions=True)
                # Restore any Unassigned trackers for these learners
                for email in valid_emails:
                    tracker = frappe.db.get_value(
                        "LMS Module Tracker",
                        {"user": email, "module": module_id},
                        ["name", "status", "progress_percentage"],
                        as_dict=True
                    )
                    if tracker and tracker.status == "Unassigned":
                        restored = "In Progress" if (tracker.progress_percentage or 0) > 0 else "Not started"
                        frappe.db.set_value("LMS Module Tracker", tracker.name, "status", restored)
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

@frappe.whitelist()
def add_single_learner(learner_json, selected_content_json="[]"):
    """
    Adds a single learner and optionally assigns modules/learning paths.
    """
    learner = json.loads(learner_json)
    selected_content = json.loads(selected_content_json)

    email = _ensure_user(learner)
    if not email:
        frappe.throw("Email is required to create a learner")

    if selected_content:
        # Wrap into the format expected by save_import_assignment
        group_mock = [{
            "learners": [learner],
            "selectedContent": selected_content
        }]
        save_import_assignment(json.dumps(group_mock))
    else:
        frappe.db.commit()

    return email

@frappe.whitelist()
def update_single_learner(email, learner_json):
    """
    Updates a single learner's basic details, settings, and department.
    """
    learner = json.loads(learner_json)

    if not frappe.db.exists("User", email):
        frappe.throw("User not found")

    user = frappe.get_doc("User", email)

    full_name = (learner.get("name") or "").strip()
    if full_name:
        name_parts = full_name.split(" ", 1)
        user.first_name = name_parts[0] or email.split("@")[0]
        user.last_name = name_parts[1] if len(name_parts) > 1 else ""
        user.save(ignore_permissions=True)

    # Update LMS User Settings
    designation = learner.get("designation", "")
    joining_date = learner.get("joiningDate") or learner.get("joining_date") or None

    settings_name = frappe.db.get_value("LMS User Settings", {"system_user": email}, "name")
    if settings_name:
        settings = frappe.get_doc("LMS User Settings", settings_name)
        if designation is not None:
            settings.designation = designation
        if joining_date is not None:
            settings.joining_date = joining_date
        settings.save(ignore_permissions=True)
    elif designation or joining_date:
        settings = frappe.new_doc("LMS User Settings")
        settings.system_user = email
        if designation:
            settings.designation = designation
        if joining_date:
            settings.joining_date = joining_date
        settings.insert(ignore_permissions=True)

    # Update LMS Team Member
    department = (learner.get("department") or "").strip()
    if department:
        current_teams = frappe.get_all("LMS Team Member", filters={"user": email}, fields=["name", "parent"])
        team_name = frappe.db.get_value("LMS Team", {"team_name": department}, "name")

        if not team_name:
            team = frappe.new_doc("LMS Team")
            team.team_name = department
            team.is_active = 1
            team.insert(ignore_permissions=True)
            team_name = team.name

        current_team_names = [t.parent for t in current_teams]
        if team_name not in current_team_names:
            # Add to new team
            team_doc = frappe.get_doc("LMS Team", team_name)
            team_doc.append("learners", {"user": email})
            team_doc.save(ignore_permissions=True)

            # Remove from old teams
            for t in current_teams:
                if t.parent != team_name:
                    frappe.delete_doc("LMS Team Member", t.name, ignore_permissions=True)

    frappe.db.commit()
    return email

@frappe.whitelist()
def delete_single_learner(email):
    """
    Deletes a learner permanently.
    Cleans up related LMS records before deleting the Frappe User.
    """
    if not frappe.db.exists("User", email):
        frappe.throw("User not found")

    # 1. Delete LMS User Settings
    settings_name = frappe.db.get_value("LMS User Settings", {"system_user": email}, "name")
    if settings_name:
        frappe.delete_doc("LMS User Settings", settings_name, ignore_permissions=True, force=1)

    # 2. Delete LMS Team Memberships
    team_members = frappe.get_all("LMS Team Member", filters={"user": email}, fields=["name", "parent"])
    for tm in team_members:
        # Also remove from parent doc's child table if needed, though delete_doc on child is usually sufficient in modern frappe
        frappe.delete_doc("LMS Team Member", tm.name, ignore_permissions=True, force=1)

    # 3. Delete Trackers
    trackers = frappe.get_all("LMS Module Tracker", filters={"user": email}, pluck="name")
    for t in trackers:
        frappe.delete_doc("LMS Module Tracker", t, ignore_permissions=True, force=1)

    lp_trackers = frappe.get_all("LMS Learning Path Tracker", filters={"user": email}, pluck="name")
    for t in lp_trackers:
        frappe.delete_doc("LMS Learning Path Tracker", t, ignore_permissions=True, force=1)

    # 4. Remove from manual assignments (Module & LP)
    # Module assignments
    mod_assignments = frappe.get_all("LMS Assignment User", filters={"user": email}, fields=["name", "parent"])
    for ma in mod_assignments:
        frappe.delete_doc("LMS Assignment User", ma.name, ignore_permissions=True, force=1)
        # Touch parent to update modified timestamp
        frappe.db.set_value("LMS Module Assignment", ma.parent, "modified", frappe.utils.now())

    # LP assignments
    lp_assignments = frappe.get_all("LMS LP Assignment User", filters={"user": email}, fields=["name", "parent"])
    for la in lp_assignments:
        frappe.delete_doc("LMS LP Assignment User", la.name, ignore_permissions=True, force=1)
        frappe.db.set_value("LMS Learning Path Assignment", la.parent, "modified", frappe.utils.now())

    # 5. Delete Quiz Submissions
    submissions = frappe.get_all("LMS Quiz Submission", filters={"user": email}, pluck="name")
    for s in submissions:
        frappe.delete_doc("LMS Quiz Submission", s, ignore_permissions=True, force=1)

    # 6. Delete the actual User (force=1 ignores LinkExists errors if there are remaining links)
    frappe.delete_doc("User", email, ignore_permissions=True, force=1)

    frappe.db.commit()
    return {"message": "success"}
