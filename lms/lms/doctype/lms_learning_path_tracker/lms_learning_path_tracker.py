# Copyright (c) 2026, Novel Office and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class LMSLearningPathTracker(Document):
	def before_save(self):
		self.update_progress()

	def on_update(self):
		"""Issue or update LP certificate after progress has been saved."""
		if self.status == "Completed":
			self.issue_lp_certificate_if_eligible()

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
			
			if mt and mt.status == "Unassigned":
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
			self.total_score = -1
			
		# Auto-update status
		if self.progress_percentage >= 100:
			self.progress_percentage = 100
			if self.status != "Completed":
				self.status = "Completed"
				self.completed_on = frappe.utils.now_datetime()
		else:
			if self.progress_percentage > 0:
				if self.status != "In Progress":
					self.status = "In Progress"
			else:
				if self.status not in ["Not started", "Not Started"]:
					self.status = "Not started"
			self.completed_on = None

			# Always revoke certificates if progress is below 100%
			certs = frappe.get_all(
				"LMS Certificate",
				filters={"learning_path": self.learning_path, "user": self.user, "status": ("in", ["Issued", "Reissued"])}
			)
			for c in certs:
				frappe.db.set_value("LMS Certificate", c.name, {
					"status": "Revoked",
					"revocation_reason": "Certification requirements changed",
					"custom_revocation_reason": "Learning path content was updated. Learner must complete the new requirements to regain certification.",
					"revoked_by": frappe.session.user if getattr(frappe.session, "user", None) else "Administrator",
					"revoked_on": frappe.utils.now_datetime()
				})
			
		if self.status in ["In Progress", "Completed"] and not self.started_on:
			self.started_on = frappe.utils.now_datetime()

	def issue_lp_certificate_if_eligible(self):
		"""Issue or reissue an LMS Certificate for this learning path if eligible."""
		try:
			lp = frappe.get_doc("LMS Learning Path", self.learning_path)
		except Exception:
			return

		if not lp.enable_certificate:
			return

		# Check passing score requirement
		passing_score = getattr(lp, "certificate_passing_percentage", None) or 0
		if passing_score > 0 and self.total_score is not None and self.total_score != -1:
			if self.total_score < passing_score:
				return

		# Check for existing LP certificate
		existing_cert = frappe.db.get_value(
			"LMS Certificate",
			{"user": self.user, "learning_path": self.learning_path},
			"name"
		)

		if existing_cert:
			cert = frappe.get_doc("LMS Certificate", existing_cert)
			if cert.status in ["Issued", "Reissued"]:
				# Already active — nothing to do
				return
			# Was revoked/expired — reissue
			cert.status = "Reissued"
			cert.issued_on = frappe.utils.nowdate()
			cert.score = self.total_score if self.total_score and self.total_score >= 0 else None
			cert.certificate_pdf = None
			cert.pdf_status = "Pending"
			cert.pdf_file_url = None
			cert.revocation_reason = None
			cert.custom_revocation_reason = None
			cert.revoked_by = None
			cert.revoked_on = None
			cert.save(ignore_permissions=True)

			# Clean up old PDFs
			old_files = frappe.get_all(
				"File",
				filters={"attached_to_doctype": "LMS Certificate", "attached_to_name": cert.name}
			)
			for f in old_files:
				frappe.delete_doc("File", f.name, ignore_permissions=True)
			return

		# Resolve template
		template_name = getattr(lp, "certificate_template", None)
		if not template_name or not frappe.db.exists("LMS Certificate Template", template_name):
			available = frappe.get_all("LMS Certificate Template", limit=1)
			if available:
				template_name = available[0].name
			else:
				# No template available — still create cert but without template
				template_name = None

		cert = frappe.new_doc("LMS Certificate")
		cert.user = self.user
		cert.learning_path = self.learning_path
		cert.lp_tracker = self.name
		cert.template = template_name
		cert.issued_on = frappe.utils.nowdate()
		cert.score = self.total_score if self.total_score is not None and self.total_score >= 0 else None
		cert.status = "Issued"
		cert.insert(ignore_permissions=True)
