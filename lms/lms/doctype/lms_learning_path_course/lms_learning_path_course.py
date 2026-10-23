import frappe
from frappe.model.document import Document


class LMSLearningPathCourse(Document):
	def on_update(self):
		self.trigger_parent_trackers()

	def on_trash(self):
		self.trigger_parent_trackers()

	def trigger_parent_trackers(self):
		if self.parent and self.parenttype == "LMS Learning Path":
			try:
				lp = frappe.get_doc("LMS Learning Path", self.parent)
				lp.check_and_trigger_trackers()
			except Exception:
				pass

