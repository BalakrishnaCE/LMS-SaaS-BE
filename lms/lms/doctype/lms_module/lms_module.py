# Copyright (c) 2026, Novel Office and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class LMSModule(Document):
	def on_update(self):
		self.check_and_trigger_trackers()

	def check_and_trigger_trackers(self):
		import frappe
		# Always trigger trackers so they recalculate total items
		trackers = frappe.get_all("LMS Module Tracker", filters={"module": self.name}, pluck="name")
		for t in trackers:
			tracker = frappe.get_doc("LMS Module Tracker", t)
			tracker.save(ignore_permissions=True)
