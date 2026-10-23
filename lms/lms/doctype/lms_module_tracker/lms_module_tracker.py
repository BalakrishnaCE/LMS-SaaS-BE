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

		# ── Build a quick lookup of content_progress by reference ────────────────
		cp_map = {cp.content_reference: cp for cp in self.get("content_progress", [])}

		# ── Collect all content items in the module & calculate chapter/lesson progress ──
		total_items = 0
		total_scored_items = 0
		SCORED_TYPES = ("LMS Quiz Content", "LMS Assessment Content")

		existing_chapters = {row.chapter: row for row in self.get("chapter_progress", []) if row.chapter}
		existing_lessons = {row.lesson: row for row in self.get("lesson_progress", []) if row.lesson}

		valid_chapters = set()
		valid_lessons = set()

		updated_chapter_rows = []
		updated_lesson_rows = []

		for ml in module_doc.get("lessons", []):
			if not ml.lesson or not frappe.db.exists("LMS Lesson", ml.lesson):
				continue
			lesson_doc = frappe.get_doc("LMS Lesson", ml.lesson)
			valid_lessons.add(ml.lesson)

			lesson_chapter_statuses = []

			for lc in lesson_doc.get("chapters", []):
				if not lc.chapter or not frappe.db.exists("LMS Chapter", lc.chapter):
					continue
				chapter_doc = frappe.get_doc("LMS Chapter", lc.chapter)
				valid_chapters.add(lc.chapter)

				ch_total_items = 0
				ch_completed_items = 0
				ch_started_items = 0
				ch_scored_items = 0
				ch_score_sum = 0.0

				for c in chapter_doc.get("contents", []):
					is_flashcard = (c.content_type == "LMS Flashcard Content")
					is_scored = (c.content_type in SCORED_TYPES)

					if not is_flashcard:
						total_items += 1
						ch_total_items += 1
					if is_scored:
						total_scored_items += 1
						ch_scored_items += 1

					cp = cp_map.get(c.content_reference)
					if cp:
						if cp.status in ("In Progress", "Completed") or (cp.last_position and float(cp.last_position or 0) > 0):
							ch_started_items += 1

						if is_scored:
							score_val = float(cp.score or 0)
							ch_score_sum += score_val
							if score_val >= passing_score and cp.status == "Completed":
								ch_completed_items += 1
						else:
							if cp.status == "Completed":
								ch_completed_items += 1

				# Determine chapter status
				if ch_total_items > 0:
					if ch_completed_items >= ch_total_items:
						ch_status = "Completed"
					elif ch_completed_items > 0 or ch_started_items > 0:
						ch_status = "In Progress"
					else:
						ch_status = "Not Started"
				else:
					if ch_started_items > 0:
						ch_status = "Completed" if ch_completed_items > 0 else "In Progress"
					else:
						ch_status = "Completed" if self.status == "Completed" else "Not Started"

				ch_score = round(ch_score_sum / ch_scored_items, 2) if ch_scored_items > 0 else 0.0
				lesson_chapter_statuses.append(ch_status)

				# Update or append chapter progress row
				if lc.chapter in existing_chapters:
					row = existing_chapters[lc.chapter]
					row.status = ch_status
					row.score = ch_score
					updated_chapter_rows.append(row)
				else:
					row = self.append("chapter_progress", {
						"chapter": lc.chapter,
						"status": ch_status,
						"score": ch_score
					})
					updated_chapter_rows.append(row)

			# Determine lesson status
			if lesson_chapter_statuses:
				if all(st == "Completed" for st in lesson_chapter_statuses):
					les_status = "Completed"
				elif any(st in ("Completed", "In Progress") for st in lesson_chapter_statuses):
					les_status = "In Progress"
				else:
					les_status = "Not Started"
			else:
				les_status = "Completed" if self.status == "Completed" else "Not Started"

			# Update or append lesson progress row
			if ml.lesson in existing_lessons:
				row = existing_lessons[ml.lesson]
				row.status = les_status
				updated_lesson_rows.append(row)
			else:
				row = self.append("lesson_progress", {
					"lesson": ml.lesson,
					"status": les_status
				})
				updated_lesson_rows.append(row)

		# Retain only valid rows
		self.set("chapter_progress", [r for r in updated_chapter_rows if r.chapter in valid_chapters])
		self.set("lesson_progress", [r for r in updated_lesson_rows if r.lesson in valid_lessons])

		# ── Count "effectively completed" items ──────────────────────────────────
		# Non-scored content (video/text/image) → done when status == "Completed"
		# Scored content (quiz/assessment)      → done only when score >= passing threshold
		#   (This means a failed quiz stays uncounted, giving correct progress %)
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
		if total_scored_items > 0:
			self.total_score = round(total_score_sum / total_scored_items, 2)
		else:
			self.total_score = -1

		# ── Determine tracker status ─────────────────────────────────────────────
		all_content_submitted = sum(
			1 for cp in self.get("content_progress", [])
			if cp.status == "Completed" and cp.content_type != "LMS Flashcard Content"
		) >= total_items and total_items > 0

		if all_content_submitted:
			is_pending_eval = self.has_pending_evaluations()

			if is_pending_eval:
				target_status = "In Progress"
			elif completed_items < total_items:
				# All content was submitted, but one or more scored items failed passing threshold
				target_status = "Failed"
			elif module_doc.is_score_required and scored_items > 0 and self.total_score < passing_score:
				target_status = "Failed"
			else:
				target_status = "Completed"

			if self.status != target_status:
				self.status = target_status
				if target_status == "Completed":
					self.completed_on = frappe.utils.now_datetime()
				else:
					self.completed_on = None
			elif target_status != "Completed":
				self.completed_on = None

			if not self.started_on:
				self.started_on = self.completed_on or frappe.utils.now_datetime()
		else:
			if self.progress_percentage > 0 or len(self.get("content_progress", [])) > 0:
				if self.status != "In Progress":
					self.status = "In Progress"
				if not self.started_on:
					self.started_on = frappe.utils.now_datetime()
			self.completed_on = None

		# Always revoke certificates if tracker is not Completed or progress is below 100%
		if self.status != "Completed" or (self.progress_percentage or 0) < 100:
			certs = frappe.get_all(
				"LMS Certificate",
				filters={
					"status": ("in", ["Issued", "Reissued"]),
					"user": self.user,
					"module": self.module,
				}
			)
			if not certs and self.name:
				certs = frappe.get_all(
					"LMS Certificate",
					filters={"enrollment": self.name, "status": ("in", ["Issued", "Reissued"])}
				)
			for c in certs:
				frappe.db.set_value("LMS Certificate", c.name, {
					"status": "Revoked",
					"revocation_reason": "Certification requirements changed",
					"custom_revocation_reason": "Module requirements not met or quiz not passed. Learner must complete all requirements to regain certification.",
					"revoked_by": frappe.session.user if frappe.session and frappe.session.user else "Administrator",
					"revoked_on": frappe.utils.now_datetime()
				})

		# If module is completed, mark all child chapter and lesson rows Completed
		if self.status == "Completed":
			for cp_row in self.get("chapter_progress", []):
				cp_row.status = "Completed"
			for lp_row in self.get("lesson_progress", []):
				lp_row.status = "Completed"

		if self.status in ["In Progress", "Completed", "Failed"] and not self.started_on:
			self.started_on = frappe.utils.now_datetime()

	def has_pending_evaluations(self):
		subs = frappe.get_all("LMS Quiz Submission", filters={"enrollment": self.name}, fields=["name", "quiz", "score"])
		for sub in subs:
			if sub.score is None:
				eval_method = frappe.db.get_value("LMS Quiz", sub.quiz, "evaluation_method")
				if eval_method == "Manual review":
					return True
		return False

	def on_update(self):
		self.update_learning_path_trackers()
		if self.status == "Completed":
			self.issue_certificate_if_eligible()

	def issue_certificate_if_eligible(self):
		if self.status != "Completed" or (self.progress_percentage or 0) < 100:
			return

		module = frappe.get_doc("LMS Module", self.module)
		if not module.enable_certificate:
			return
			
		passing_score = module.certificate_passing_percentage or 60
		# If total_score is -1, it means there are no scorable items, so passing_score check should be bypassed
		if self.total_score != -1 and (self.total_score or 0) < passing_score:
			return
			
		# Check if certificate already exists
		existing_cert = frappe.db.get_value("LMS Certificate", {"user": self.user, "module": self.module}, "name")
		if existing_cert:
			cert = frappe.get_doc("LMS Certificate", existing_cert)
			if cert.status in ["Issued", "Reissued"]:
				return
			
			cert.status = "Reissued"
			cert.issued_on = frappe.utils.nowdate()
			cert.score = self.total_score
			cert.save(ignore_permissions=True)
			return
			
		template_name = module.certificate_template or "Classic Template"
		if not frappe.db.exists("LMS Certificate Template", template_name):
			available = frappe.get_all("LMS Certificate Template", limit=1)
			if available:
				template_name = available[0].name
			else:
				return
			
		cert = frappe.new_doc("LMS Certificate")
		
		cert.user = self.user
		cert.module = self.module
		cert.enrollment = self.name
		cert.template = template_name
		cert.issued_on = frappe.utils.nowdate()
		cert.score = self.total_score
		cert.status = "Issued"
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


def backfill_tracker_progress(tracker_name=None):
	if tracker_name:
		trackers = [tracker_name]
	else:
		trackers = frappe.get_all(
			"LMS Module Tracker",
			filters={"status": ("in", ["In Progress", "Completed"])},
			pluck="name"
		)

	updated = 0
	for t_name in trackers:
		try:
			doc = frappe.get_doc("LMS Module Tracker", t_name)
			doc.flags.ignore_version = True
			doc.save(ignore_permissions=True)
			updated += 1
		except Exception as e:
			frappe.log_error(f"Error backfilling tracker {t_name}", str(e))

	frappe.db.commit()
	return f"Successfully updated {updated} trackers."


