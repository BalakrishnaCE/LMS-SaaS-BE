import os
import json

doctype_dir = '/home/frappe/frappe-bench/apps/lms/lms/lms/doctype/'

def generate_description(label, fieldtype, options):
    if not label:
        return ""
        
    if fieldtype == "Link":
        return f"Link to the corresponding {options}."
    elif fieldtype == "Table":
        return f"Child table for {options}."
    elif fieldtype == "Check":
        return f"Toggle to enable or disable {label.lower()}."
    elif fieldtype == "Select":
        return f"Select the {label.lower()} from the dropdown options."
    elif fieldtype in ["Data", "Text", "Text Editor", "Small Text"]:
        return f"Enter the {label.lower()}."
    elif fieldtype == "Float" or fieldtype == "Int":
        return f"Numeric value for {label.lower()}."
    elif fieldtype == "Attach" or fieldtype == "Attach Image":
        return f"Upload the {label.lower()} file."
    elif fieldtype == "Datetime" or fieldtype == "Date":
        return f"The exact {label.lower()}."
    elif fieldtype == "Dynamic Link":
        return f"Dynamically links to a specific record based on the type."
    else:
        return f"Determines the {label.lower()}."

updated_count = 0

for dt_folder in os.listdir(doctype_dir):
    dt_path = os.path.join(doctype_dir, dt_folder, f"{dt_folder}.json")
    if not os.path.exists(dt_path):
        continue
        
    with open(dt_path, 'r') as f:
        dt_json = json.load(f)
        
    modified = False
    for field in dt_json.get('fields', []):
        # Skip if it already has a description that isn't empty
        if field.get('description') and field['description'].strip() != "":
            continue
            
        label = field.get('label', field.get('fieldname', ''))
        fieldtype = field.get('fieldtype', '')
        options = field.get('options', '')
        
        auto_desc = generate_description(label, fieldtype, options)
        if auto_desc:
            field['description'] = auto_desc
            modified = True
            updated_count += 1
            
    if modified:
        with open(dt_path, 'w') as f:
            json.dump(dt_json, f, indent=1)

print(f"Successfully auto-generated and injected {updated_count} missing descriptions across all LMS DocTypes.")
