# Copyright (c) 2026, Novel Office and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class LMSLearningPathAssignment(Document):
    def on_update(self):
        self.create_trackers()

    def after_insert(self):
        self.create_trackers()

    def create_trackers(self):
        users = set()
        
        if self.assignment_type == "Manual":
            for row in self.learners:
                if row.user:
                    users.add(row.user)
                    
        elif self.assignment_type == "Team":
            for row in self.assigned_teams:
                if row.team:
                    members = frappe.get_all("LMS Team Member", filters={"parent": row.team}, fields=["user"])
                    for member in members:
                        if member.user:
                            users.add(member.user)
                            
        elif self.assignment_type == "Everyone":
            lms_roles = frappe.get_all("Has Role", filters={"role": ["in", ["LMS-Learner", "LMS-TL"]]}, fields=["parent"])
            valid_users = [r.parent for r in lms_roles if r.parent not in ["Administrator", "Guest"]]
            all_users = frappe.get_all(
                "User",
                filters={
                    "enabled": 1,
                    "name": ["in", valid_users] if valid_users else ["in", ["__nobody__"]]
                },
                fields=["name"]
            )
            for u in all_users:
                users.add(u.name)
                
        # Find existing trackers
        existing_trackers = frappe.get_all("LMS Learning Path Tracker", filters={"learning_path": self.learning_path}, fields=["name", "user", "status", "progress_percentage"])
        existing_map = {t.user: t for t in existing_trackers}
        
        # Mark trackers as Unassigned for users no longer assigned
        for t in existing_trackers:
            if t.user not in users and t.status != "Unassigned":
                frappe.db.set_value("LMS Learning Path Tracker", t.name, "status", "Unassigned")
                
        # Create trackers for new users or restore Unassigned ones
        for user in users:
            if user not in existing_map:
                tracker = frappe.new_doc("LMS Learning Path Tracker")
                tracker.user = user
                tracker.learning_path = self.learning_path
                tracker.status = "Not started"
                tracker.progress_percentage = 0
                tracker.insert(ignore_permissions=True)
            else:
                # Restore if it was Unassigned
                tracker = existing_map[user]
                if tracker.status == "Unassigned":
                    prog = tracker.progress_percentage or 0
                    restored = "Completed" if prog >= 100 else ("In Progress" if prog > 0 else "Not started")
                    frappe.db.set_value("LMS Learning Path Tracker", tracker.name, "status", restored)
