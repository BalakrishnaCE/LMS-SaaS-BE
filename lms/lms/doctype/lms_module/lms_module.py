# Copyright (c) 2026, Novel Office and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class LMSModule(Document):
	def validate(self):
		import frappe
		if self.is_new() and frappe.db.exists("LMS Module", self.module_name):
			frappe.throw(f"A Module named '{self.module_name}' already exists. Please choose a different name.")

	def before_rename(self, old_name, new_name, merge=False):
		import frappe
		if frappe.db.exists("LMS Module", new_name):
			frappe.throw(f"A Module named '{new_name}' already exists. Please choose a different name.")

	def on_update(self):
		self.check_and_trigger_trackers()

	def check_and_trigger_trackers(self):
		import frappe
		# Always trigger trackers so they recalculate total items
		trackers = frappe.get_all("LMS Module Tracker", filters={"module": self.name}, pluck="name")
		for t in trackers:
			tracker = frappe.get_doc("LMS Module Tracker", t)
			tracker.flags.ignore_version = True
			tracker.save(ignore_permissions=True)
