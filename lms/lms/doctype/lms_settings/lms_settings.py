# Copyright (c) 2026, Novel Office and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class LMSSettings(Document):
	def on_update(self):
		# Sync brand settings to the high-speed Redis Cache.
		# The React app reads from this cache for instant loading without a DB hit.
		cache = frappe.cache()

		if self.primary_color:
			cache.set_value("theme_color", self.primary_color)

		if self.primary_logo:
			cache.set_value("brand_primary_logo", self.primary_logo)

		if self.light_logo:
			cache.set_value("brand_light_logo", self.light_logo)

		if self.app_icon:
			cache.set_value("brand_app_icon", self.app_icon)

		if self.default_theme:
			cache.set_value("brand_default_theme", self.default_theme)

