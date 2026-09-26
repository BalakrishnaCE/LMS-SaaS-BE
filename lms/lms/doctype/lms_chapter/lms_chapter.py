# Copyright (c) 2026, Novel Office and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class LMSChapter(Document):
	def validate(self):
		import frappe
		if hasattr(self, "contents") and self.contents:
			for row in reversed(self.contents):
				if not row.content_type or not row.content_reference or not frappe.db.exists(row.content_type, row.content_reference):
					self.remove(row)

	def on_update(self):
		self.update_lessons()

	def update_lessons(self):
		import frappe
		lessons = frappe.get_all("LMS Lesson Chapter", filters={"chapter": self.name}, pluck="parent")
		for lesson_name in set(lessons):
			lesson_doc = frappe.get_doc("LMS Lesson", lesson_name)
			lesson_doc.update_module_trackers()
