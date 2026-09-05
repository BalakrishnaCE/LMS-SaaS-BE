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
                            
        for user in users:
            exists = frappe.db.exists("LMS Learning Path Tracker", {"user": user, "learning_path": self.learning_path})
            if not exists:
                tracker = frappe.new_doc("LMS Learning Path Tracker")
                tracker.user = user
                tracker.learning_path = self.learning_path
                tracker.status = "Not started"
                tracker.progress_percentage = 0
                tracker.insert(ignore_permissions=True)
