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

		# Auto-update tracker status based on progress
		if self.progress_percentage >= 100:
			self.progress_percentage = 100
			if self.status != "Completed":
				self.status = "Completed"
				self.completed_on = frappe.utils.now_datetime()
		elif self.progress_percentage > 0 and self.status == "Not Started":
			self.status = "In Progress"

		if self.status in ["In Progress", "Completed"] and not self.started_on:
			self.started_on = frappe.utils.now_datetime()
			
		# Calculate total score from scored items
		scored_items = 0
		total_score_sum = 0
		for cp in self.get("content_progress", []):
			if cp.score is not None and cp.score >= 0:
				scored_items += 1
				total_score_sum += cp.score
		
		if scored_items > 0:
			self.total_score = round(total_score_sum / scored_items, 2)
