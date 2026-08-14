# Copyright (c) 2026, Novel Office and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class LMSSettings(Document):
	def on_update(self):
		# Sync the primary_color to the high-speed Redis Cache
		# The React app reads from this cache for instant loading
		if self.primary_color:
			frappe.cache().set_value("theme_color", self.primary_color)

