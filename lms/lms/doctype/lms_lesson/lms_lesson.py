# Copyright (c) 2026, Novel Office and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class LMSLesson(Document):
	def on_update(self):
		self.update_module_trackers()

	def update_module_trackers(self):
		import frappe
		modules = frappe.get_all("LMS Module Lesson Child", filters={"lesson": self.name}, pluck="parent")
		for module_name in set(modules):
			module_doc = frappe.get_doc("LMS Module", module_name)
			module_doc.check_and_trigger_trackers()
