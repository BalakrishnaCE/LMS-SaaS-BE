import os
import json
import re

schema_file = 'schema.txt'
doctype_dir = '/home/frappe/frappe-bench/apps/lms/lms/lms/doctype/'

def normalize_name(name):
    return name.lower().replace(' ', '_').strip()

# Parse schema
schema_data = {}
current_doctype = None
current_field = None

with open(schema_file, 'r') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        
        # Match Doctype header e.g., "1. LMS TEAM (Master DocType)" or "1a. LMS TEAM LEAD (Child Table)"
        dt_match = re.match(r'^\d+[a-z]?\.\s+([A-Z0-9\s_]+)\s*\(.*$', line)
        if dt_match:
            dt_name = dt_match.group(1).strip()
            # Special case for Quiz Child connector
            if dt_name == 'LMS QUIZ CHILD':
                pass # it's fine
            current_doctype = normalize_name(dt_name)
            schema_data[current_doctype] = {}
            current_field = None
            continue
            
        # Match Fieldname e.g., "Fieldname: team_name"
        fn_match = re.match(r'^Fieldname:\s*(.+)$', line, re.IGNORECASE)
        if fn_match and current_doctype:
            current_field = fn_match.group(1).strip()
            if current_field not in schema_data[current_doctype]:
                schema_data[current_doctype][current_field] = ""
            continue
            
        # Match Notes e.g., "Notes: e.g., "Marketing", "Engineering""
        note_match = re.match(r'^Notes:\s*(.+)$', line, re.IGNORECASE)
        if note_match and current_doctype and current_field:
            note_text = note_match.group(1).strip()
            schema_data[current_doctype][current_field] = note_text
            continue

print("=== Audit Results ===")
missing_doctypes = []
missing_fields = []
updated_fields = 0

for dt, fields in schema_data.items():
    dt_path = os.path.join(doctype_dir, dt, f"{dt}.json")
    if not os.path.exists(dt_path):
        missing_doctypes.append(dt)
        continue
        
    with open(dt_path, 'r') as f:
        dt_json = json.load(f)
        
    json_fields = {f['fieldname']: f for f in dt_json.get('fields', [])}
    
    modified = False
    for fn, note in fields.items():
        if fn not in json_fields:
            missing_fields.append(f"{dt} -> {fn}")
        elif note:
            json_fields[fn]['description'] = note
            modified = True
            updated_fields += 1
            
    if modified:
        with open(dt_path, 'w') as f:
            json.dump(dt_json, f, indent=1)

print(f"\nMissing DocTypes ({len(missing_doctypes)}):")
for md in missing_doctypes:
    print(f"  - {md}")

print(f"\nMissing Fields ({len(missing_fields)}):")
for mf in missing_fields:
    print(f"  - {mf}")
    
print(f"\nSuccessfully injected descriptions for {updated_fields} fields across the system.")
