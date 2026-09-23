# Copyright (c) 2026, Novel Office and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.model.naming import make_autoname


class LMSCertificate(Document):
	def autoname(self):
		if not self.name:
			ref_no = "CERT-.####"
			if self.module:
				try:
					mod = frappe.get_doc("LMS Module", self.module)
					if mod.certificate_reference_number:
						ref_no = mod.certificate_reference_number
				except Exception:
					pass
					
			if "#" not in ref_no:
				ref_no = f"{ref_no}-.####"
				
			try:
				self.name = make_autoname(ref_no)
			except Exception:
				self.name = f"CERT-{frappe.generate_hash(length=8).upper()}"
