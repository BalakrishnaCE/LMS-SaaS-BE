# Copyright (c) 2026, Novel Office and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class LMSChapter(Document):
	def on_update(self):
		self.update_lessons()

	def update_lessons(self):
		import frappe
		lessons = frappe.get_all("LMS Lesson Chapter", filters={"chapter": self.name}, pluck="parent")
		for lesson_name in set(lessons):
			lesson_doc = frappe.get_doc("LMS Lesson", lesson_name)
			lesson_doc.update_module_trackers()
