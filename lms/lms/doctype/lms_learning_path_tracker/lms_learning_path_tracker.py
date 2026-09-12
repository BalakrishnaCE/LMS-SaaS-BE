# Copyright (c) 2026, Novel Office and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class LMSLearningPathTracker(Document):
	def before_save(self):
		self.update_progress()

	def update_progress(self):
		if not self.learning_path or not self.user:
			return

		# Get all modules in this learning path
		path_courses = frappe.get_all("LMS Learning Path Course", filters={"parent": self.learning_path}, fields=["module"])
		module_names = [pc.module for pc in path_courses]
		
		total_modules = len(module_names)
		if total_modules == 0:
			self.progress_percentage = 0
			self.total_score = 0
			return

		# Get module trackers for this user and these modules
		module_trackers = frappe.get_all(
			"LMS Module Tracker",
			filters={"user": self.user, "module": ("in", module_names)},
			fields=["module", "status", "total_score", "progress_percentage"]
		)
		
		tracker_map = {mt.module: mt for mt in module_trackers}
		
		completed_modules = 0
		scored_modules = 0
		total_score_sum = 0
		total_progress_sum = 0
		valid_modules_count = 0
		
		self.set("module_progress", [])
		
		for mod in module_names:
			mt = tracker_map.get(mod)
			
			if mt and mt.status == "Excluded":
				continue
				
			valid_modules_count += 1
			
			status = mt.status if mt else "Not Started"
			if status == "Not started":
				status = "Not Started"
			score = mt.total_score if mt else 0.0
			
			self.append("module_progress", {
				"module": mod,
				"status": status,
				"score": score
			})
			
			if mt and mt.progress_percentage is not None:
				total_progress_sum += mt.progress_percentage
				
			if status == "Completed":
				completed_modules += 1
				
			if mt and mt.total_score is not None and mt.total_score >= 0:
				scored_modules += 1
				total_score_sum += mt.total_score
				
		if valid_modules_count > 0:
			self.progress_percentage = round((total_progress_sum / valid_modules_count), 2)
		else:
			self.progress_percentage = 0
		
		if scored_modules > 0:
			self.total_score = round(total_score_sum / scored_modules, 2)
		else:
			self.total_score = 0.0
			
		# Auto-update status
		if self.progress_percentage >= 100:
			self.progress_percentage = 100
			if self.status != "Completed":
				self.status = "Completed"
				self.completed_on = frappe.utils.now_datetime()
		elif self.progress_percentage > 0 and self.status in ["Not Started", "Not started"]:
			self.status = "In Progress"
			
		if self.status in ["In Progress", "Completed"] and not self.started_on:
			self.started_on = frappe.utils.now_datetime()
