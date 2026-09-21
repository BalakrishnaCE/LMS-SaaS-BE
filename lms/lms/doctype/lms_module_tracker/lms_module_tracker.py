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

		module_doc = frappe.get_doc("LMS Module", self.module)
		passing_score = module_doc.certificate_passing_percentage or 0

		# ── Collect all content items in the module (excluding flashcards) ──────
		total_items = 0
		for ml in module_doc.get("lessons", []):
			if not ml.lesson: continue
			lesson_doc = frappe.get_doc("LMS Lesson", ml.lesson)
			for lc in lesson_doc.get("chapters", []):
				if not lc.chapter: continue
				chapter_doc = frappe.get_doc("LMS Chapter", lc.chapter)
				for c in chapter_doc.get("contents", []):
					if c.content_type != "LMS Flashcard Content":
						total_items += 1

		# ── Build a quick lookup of content_progress by reference ────────────────
		cp_map = {cp.content_reference: cp for cp in self.get("content_progress", [])}

		# ── Count "effectively completed" items ──────────────────────────────────
		# Non-scored content (video/text/image) → done when status == "Completed"
		# Scored content (quiz/assessment)      → done only when score >= passing threshold
		#   (This means a failed quiz stays uncounted, giving correct progress %)
		SCORED_TYPES = ("LMS Quiz Content", "LMS Assessment Content")
		completed_items = 0
		scored_items = 0
		total_score_sum = 0.0

		for cp in self.get("content_progress", []):
			if cp.content_type == "LMS Flashcard Content":
				continue
			if cp.content_type in SCORED_TYPES:
				scored_items += 1
				total_score_sum += float(cp.score or 0)
				# Counts toward progress only when passing threshold is met
				if float(cp.score or 0) >= passing_score:
					completed_items += 1
			else:
				if cp.status == "Completed":
					completed_items += 1

		if total_items == 0:
			self.progress_percentage = 0
		else:
			self.progress_percentage = round((completed_items / total_items) * 100)

		# ── Total score (average of all scored items) ────────────────────────────
		if scored_items > 0:
			self.total_score = round(total_score_sum / scored_items, 2)
		else:
			self.total_score = self.progress_percentage

		# ── Determine tracker status ─────────────────────────────────────────────
		all_content_submitted = sum(
			1 for cp in self.get("content_progress", [])
			if cp.status == "Completed" and cp.content_type != "LMS Flashcard Content"
		) >= total_items and total_items > 0

		if all_content_submitted:
			is_pending_eval = self.has_pending_evaluations()

			if is_pending_eval:
				target_status = "In Progress"
			elif module_doc.is_score_required and scored_items > 0:
				target_status = "Failed" if self.total_score < passing_score else "Completed"
			else:
				target_status = "Completed"

			if self.status != target_status:
				self.status = target_status
				if target_status == "Completed":
					self.completed_on = frappe.utils.now_datetime()
		elif (self.progress_percentage > 0 or len(self.get("content_progress", [])) > 0) and self.status == "Not started":
			self.status = "In Progress"

		if self.status in ["In Progress", "Completed", "Failed"] and not self.started_on:
			self.started_on = frappe.utils.now_datetime()

	def has_pending_evaluations(self):
		subs = frappe.get_all("LMS Quiz Submission", filters={"enrollment": self.name}, fields=["name", "quiz", "score"])
		for sub in subs:
			if sub.score is None or sub.score == 0.0:
				eval_method = frappe.db.get_value("LMS Quiz", sub.quiz, "evaluation_method")
				if eval_method == "Manual review":
					return True
		return False

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
			
		template_name = module.certificate_template or "Classic Template"
		if not frappe.db.exists("LMS Certificate Template", template_name):
			available = frappe.get_all("LMS Certificate Template", limit=1)
			if available:
				template_name = available[0].name
			else:
				return
			
		cert = frappe.new_doc("LMS Certificate")
		
		ref_no = module.certificate_reference_number or "CERT-.####"
		# Frappe requires dots around the hashes, e.g. .####.
		# If user typed #### without dots, auto-correct it for them
		import re
		if "#" in ref_no:
			ref_no = re.sub(r'(?<!\.)(#+)(?!\.)', r'.\1.', ref_no)
		
		try:
			from frappe.model.naming import make_autoname
			cert.certificate_id = make_autoname(ref_no)
		except Exception:
			cert.certificate_id = f"CERT-{frappe.generate_hash(length=8).upper()}"
			
		cert.user = self.user
		cert.module = self.module
		cert.enrollment = self.name
		cert.template = template_name
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

