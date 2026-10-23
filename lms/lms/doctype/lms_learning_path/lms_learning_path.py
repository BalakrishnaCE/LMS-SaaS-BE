import frappe
from frappe.model.document import Document


class LMSLearningPath(Document):
	def on_update(self):
		if not self.flags.ignore_trackers:
			self.check_and_trigger_trackers()

	def check_and_trigger_trackers(self):
		"""
		Recalculates progress for all learning path trackers assigned to this path.
		If modules were added or removed, tracker.save() recomputes progress percentage
		and automatically revokes active certificates if progress dropped below 100%.
		"""
		trackers = frappe.get_all("LMS Learning Path Tracker", filters={"learning_path": self.name}, pluck="name")
		for t in trackers:
			try:
				tracker = frappe.get_doc("LMS Learning Path Tracker", t)
				tracker.save(ignore_permissions=True)
			except Exception as e:
				frappe.log_error(title=f"Error updating LP tracker {t}", message=str(e))


