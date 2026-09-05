# Copyright (c) 2026, Novel Office and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class LMSModuleAssignment(Document):
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
                
        for user in users:
            exists = frappe.db.exists("LMS Module Tracker", {"user": user, "module": self.module})
            if not exists:
                tracker = frappe.new_doc("LMS Module Tracker")
                tracker.user = user
                tracker.module = self.module
                tracker.status = "Not started"
                tracker.progress_percentage = 0
                tracker.insert(ignore_permissions=True)
