# Copyright (c) 2026, Novel Office and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class LMSQuizQuestion(Document):
	def validate(self):
		if self.question_type in ["Scenario Based", "Subjective"]:
			total_score = 0
			for opt in self.options:
				total_score += opt.score or 0
			self.score = total_score
