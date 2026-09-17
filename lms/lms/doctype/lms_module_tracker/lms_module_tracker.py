# Copyright (c) 2026, Novel Office and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class LMSModuleTracker(Document):
	def before_save(self):
		self.update_progress()

	def update_progress(self):
		if not self.module:
			return

		# Count total items in the module safely
		total_items = 0
		module_doc = frappe.get_doc("LMS Module", self.module)
		for ml in module_doc.get("lessons", []):
			if not ml.lesson: continue
			lesson_doc = frappe.get_doc("LMS Lesson", ml.lesson)
			for lc in lesson_doc.get("chapters", []):
				if not lc.chapter: continue
				chapter_doc = frappe.get_doc("LMS Chapter", lc.chapter)
				for c in chapter_doc.get("contents", []):
					if c.content_type != "LMS Flashcard Content":
						total_items += 1

		if total_items == 0:
			self.progress_percentage = 0
		else:
			# Count completed items in the tracker
			completed_items = sum(1 for cp in self.get("content_progress", []) if cp.status == "Completed" and cp.content_type != "LMS Flashcard Content")
			self.progress_percentage = round((completed_items / total_items) * 100)

		# Calculate total score from scored items
		scored_items = 0
		total_score_sum = 0
		for cp in self.get("content_progress", []):
			if cp.content_type in ("LMS Quiz Content", "LMS Assessment Content"):
				scored_items += 1
				total_score_sum += float(cp.score or 0)
		
		if scored_items > 0:
			self.total_score = round(total_score_sum / scored_items, 2)
		else:
			self.total_score = 0

		# Auto-update tracker status based on progress
		if self.progress_percentage >= 100:
			self.progress_percentage = 100
			
			is_failed = False
			if module_doc.is_score_required:
				passing_score = module_doc.certificate_passing_percentage or 0
				if self.total_score < passing_score:
					is_failed = True
					
			target_status = "Failed" if is_failed else "Completed"
			
			if self.status != target_status:
				self.status = target_status
				if target_status == "Completed":
					self.completed_on = frappe.utils.now_datetime()
		elif (self.progress_percentage > 0 or len(self.get("content_progress", [])) > 0) and self.status == "Not started":
			self.status = "In Progress"

		if self.status in ["In Progress", "Completed", "Failed"] and not self.started_on:
			self.started_on = frappe.utils.now_datetime()

	def on_update(self):
		self.update_learning_path_trackers()
		if self.status == "Completed":
			self.issue_certificate_if_eligible()

	def issue_certificate_if_eligible(self):
		module = frappe.get_doc("LMS Module", self.module)
		if not module.enable_certificate:
			return
			
		passing_score = module.certificate_passing_percentage or 60
		if (self.total_score or 0) < passing_score:
			return
			
		# Check if certificate already exists
		exists = frappe.db.exists("LMS Certificate", {"user": self.user, "module": self.module})
		if exists:
			return
			
		cert = frappe.new_doc("LMS Certificate")
		cert.certificate_id = f"CERT-{frappe.generate_hash(length=8).upper()}"
		cert.user = self.user
		cert.module = self.module
		cert.enrollment = self.name
		cert.template = module.certificate_template or "Classic Template"
		cert.issued_on = frappe.utils.nowdate()
		cert.score = self.total_score
		cert.is_valid = 1
		cert.insert(ignore_permissions=True)

	def update_learning_path_trackers(self):
		paths_with_module = frappe.get_all("LMS Learning Path Course", filters={"module": self.module}, fields=["parent"])
		path_names = [p.parent for p in paths_with_module]
		
		if not path_names:
			return
			
		lp_trackers = frappe.get_all("LMS Learning Path Tracker", filters={"user": self.user, "learning_path": ("in", path_names)}, fields=["name"])
		
		for lpt in lp_trackers:
			tracker = frappe.get_doc("LMS Learning Path Tracker", lpt.name)
			tracker.save(ignore_permissions=True)

