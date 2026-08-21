import frappe
import json
from frappe.utils import today, add_days, getdate, now

@frappe.whitelist(allow_guest=True)
def get_ai_insights(module_id):
    trackers = frappe.get_all(
        "LMS Module Tracker",
        filters={"module": module_id},
        fields=["status", "user", "total_score", "started_on", "completed_on"]
    )

    total = len(trackers)
    if total == 0:
        return {"insights": [
            "No learner data yet. Assign this module to learners to see insights."
        ]}

    completed = [t for t in trackers if t.status == "Completed"]
    in_prog   = [t for t in trackers if t.status == "In Progress"]
    not_started = total - len(completed) - len(in_prog)

    insights = []

    completion_rate = round(len(completed) / total * 100)
    if completion_rate >= 80:
        insights.append(f"{completion_rate}% of learners have completed this module — excellent engagement!")
    elif completion_rate >= 50:
        insights.append(f"{completion_rate}% completion rate. Consider sending a reminder to the remaining learners.")
    else:
        insights.append(f"Only {completion_rate}% completion rate. This module may need attention — consider reviewing its difficulty or length.")

    scores = [t.total_score for t in completed if t.total_score is not None]
    if scores:
        avg_score = round(sum(scores) / len(scores))
        if avg_score < 60:
            insights.append(f"Average assessment score is {avg_score}% — learners may be struggling with the content.")
        elif avg_score >= 85:
            insights.append(f"Strong average assessment score of {avg_score}% among completions.")
        else:
            insights.append(f"Average assessment score is {avg_score}%.")

    if not_started > 0:
        insights.append(f"{not_started} learner{'s' if not_started > 1 else ''} haven't started yet. A nudge notification could help.")

    stalled = [t for t in in_prog if not t.total_score]
    if len(stalled) > 0:
        insights.append(f"{len(stalled)} learner{'s' if len(stalled) > 1 else ''} started but haven't completed any assessments.")

    return {"insights": insights[:4]}


@frappe.whitelist(allow_guest=True)
def get_assessment_analytics(module_id):
    import re
    module = frappe.get_doc("LMS Module", module_id)
    if not module.final_assessments:
        return {"stats": {"passRate": 0, "averageScore": 0, "learnersRetested": 0, "retestPercentage": 0}, "missedQuestion": None, "analytics": []}
    
    quiz_name = module.final_assessments[0].assessment
    if not quiz_name:
        return {"stats": {"passRate": 0, "averageScore": 0, "learnersRetested": 0, "retestPercentage": 0}, "missedQuestion": None, "analytics": []}
    
    trackers = frappe.get_all("LMS Module Tracker", filters={"module": module_id}, pluck="name")
    if not trackers:
        return {"stats": {"passRate": 0, "averageScore": 0, "learnersRetested": 0, "retestPercentage": 0}, "missedQuestion": None, "analytics": []}
        
    submissions = frappe.get_all("LMS Quiz Submission", 
        filters={"quiz": quiz_name, "enrollment": ["in", trackers]},
        fields=["name", "user", "score", "passed"]
    )
    
    if not submissions:
        return {"stats": {"passRate": 0, "averageScore": 0, "learnersRetested": 0, "retestPercentage": 0}, "missedQuestion": None, "analytics": []}

    user_submissions = {}
    total_score = 0
    passed_count = 0

    for sub in submissions:
        total_score += sub.score
        if sub.passed:
            passed_count += 1
            
        if sub.user not in user_submissions:
            user_submissions[sub.user] = []
        user_submissions[sub.user].append(sub)

    unique_learners = len(user_submissions)
    unique_passed = sum(1 for user, subs in user_submissions.items() if any(s.passed for s in subs))
    passRate = round((unique_passed / unique_learners) * 100) if unique_learners > 0 else 0
    averageScore = round(total_score / len(submissions)) if submissions else 0
    learnersRetested = sum(1 for user, subs in user_submissions.items() if len(subs) > 1)
    retestPercentage = round((learnersRetested / unique_learners) * 100) if unique_learners > 0 else 0
    
    sub_names = [s.name for s in submissions]
    responses = frappe.get_all("LMS Quiz Response", 
        filters={"parent": ["in", sub_names]},
        fields=["question", "is_correct"]
    )
    
    question_stats = {}
    for r in responses:
        q = r.question
        if q not in question_stats:
            question_stats[q] = {"total": 0, "correct": 0}
        question_stats[q]["total"] += 1
        if r.is_correct:
            question_stats[q]["correct"] += 1
            
    analytics = []
    most_missed = None
    highest_miss_rate = -1

    if question_stats:
        questions = frappe.get_all("LMS Quiz Question", 
            filters={"name": ["in", list(question_stats.keys())]},
            fields=["name", "question_text", "question_type"]
        )
        
        for q in questions:
            stats = question_stats.get(str(q.name), {"total": 0, "correct": 0})
            pass_pct = round((stats["correct"] / stats["total"]) * 100) if stats["total"] > 0 else 0
            miss_rate = 100 - pass_pct
            
            q_type_label = "Multiple Choice"
            if q.question_type == "Single Choice":
                q_type_label = "Multiple Choice"
            elif q.question_type == "Multiple Choice":
                q_type_label = "Multiple Selection"
            elif q.question_type == "True/False":
                q_type_label = "True/False"
                
            raw_text = re.sub(r'<[^>]+>', '', q.question_text or '').strip()

            is_most_missed = False
            if miss_rate > highest_miss_rate and miss_rate > 0:
                highest_miss_rate = miss_rate
                most_missed = {
                    "id": str(q.name),
                    "text": "Most Missed Question",
                    "question": raw_text[:97] + "..." if len(raw_text) > 100 else raw_text,
                    "percentage": miss_rate
                }
                
            analytics.append({
                "id": str(q.name),
                "question": raw_text,
                "type": q_type_label,
                "passRate": pass_pct,
                "isMostMissed": False
            })
            
        if most_missed:
            for a in analytics:
                if a["id"] == most_missed["id"]:
                    a["isMostMissed"] = True

    return {
        "stats": {
            "passRate": passRate,
            "averageScore": averageScore,
            "learnersRetested": learnersRetested,
            "retestPercentage": retestPercentage
        },
        "missedQuestion": most_missed,
        "analytics": analytics
    }


@frappe.whitelist()
def update_question(question_id, question_text, options, explanation=""):
    import json
    if isinstance(options, str):
        options = json.loads(options)
        
    doc = frappe.get_doc("LMS Quiz Question", question_id)
    doc.question_text = question_text
    doc.explanation = explanation
    
    doc.set("options", [])
    for opt in options:
        doc.append("options", {
            "option_text": opt.get("text"),
            "is_correct": opt.get("is_correct", 0)
        })
        
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return "success"


@frappe.whitelist()
def delete_question(quiz_name, question_id):
    if frappe.db.exists("LMS Quiz", quiz_name):
        quiz = frappe.get_doc("LMS Quiz", quiz_name)
        new_questions = [q for q in quiz.questions if str(q.quiz_question) != str(question_id)]
        quiz.set("questions", new_questions)
        quiz.save(ignore_permissions=True)
        
    frappe.db.sql("DELETE FROM `tabLMS Quiz Response` WHERE question=%s", (question_id,))
    frappe.delete_doc("LMS Quiz Question", question_id, ignore_permissions=True, force=1)
    frappe.db.commit()
    return "success"


@frappe.whitelist(allow_guest=False)
def update_module_settings(module_id, settings):
    import json
    if not frappe.has_permission("LMS Module", "write", doc=module_id):
        frappe.throw("Not permitted", frappe.PermissionError)
        
    module = frappe.get_doc("LMS Module", module_id)
    
    try:
        settings_dict = json.loads(settings)
        
        for key, value in settings_dict.items():
            if module.meta.has_field(key):
                module.db_set(key, 1 if value else 0)
                
        return {"message": "success"}
    except Exception as e:
        frappe.log_error(f"Error in update_module_settings: {str(e)}")
        return {"error": str(e)}



def _build_content_snapshot(module_doc):
    """
    Builds a complete JSON-serialisable snapshot of all content for a module.
    Captures: module settings + lessons + chapters + chapter content blocks.
    """
    snapshot = {
        "module_settings": {
            "module_name": module_doc.module_name,
            "description": module_doc.description or "",
            "image": module_doc.image or "",
            "is_mandatory": int(module_doc.is_mandatory or 0),
            "is_sequential": int(getattr(module_doc, "is_sequential", 0)),
            "allow_skip": int(getattr(module_doc, "allow_skip", 0)),
            "enable_discussion": int(getattr(module_doc, "enable_discussion", 0)),
            "enable_ai_flashcards": int(getattr(module_doc, "enable_ai_flashcards", 0)),
            "enable_certificate": int(getattr(module_doc, "enable_certificate", 0)),
        },
        "lessons": []
    }

    lesson_names = [l.lesson for l in module_doc.get("lessons", []) if l.lesson]
    for lesson_name in lesson_names:
        try:
            lesson = frappe.get_doc("LMS Lesson", lesson_name)
            lesson_data = {
                "name": lesson.name,
                "lesson_name": lesson.lesson_name,
                "description": lesson.description or "",
                "chapters": []
            }

            chapter_links = frappe.db.get_all(
                "LMS Lesson Chapter",
                filters={"parent": lesson_name},
                fields=["chapter", "idx"],
                order_by="idx asc"
            )
            for cl in chapter_links:
                if not cl.chapter:
                    continue
                try:
                    chapter = frappe.get_doc("LMS Chapter", cl.chapter)
                    chapter_data = {
                        "name": chapter.name,
                        "title": chapter.title,
                        "contents": []
                    }
                    content_rows = frappe.db.get_all(
                        "LMS Chapter Content",
                        filters={"parent": chapter.name, "parenttype": "LMS Chapter"},
                        fields=["name", "content_type", "content_data", "order", "content_reference"],
                        order_by="`order` asc"
                    )
                    for row in content_rows:
                        # Fetch the actual content document
                        actual_content = {}
                        if row.content_type and row.content_reference:
                            try:
                                doc = frappe.get_doc(row.content_type, row.content_reference)
                                # Exclude system fields
                                actual_content = {k: v for k, v in doc.as_dict().items() if k not in ["name", "creation", "modified", "modified_by", "owner", "docstatus", "idx"]}
                            except Exception:
                                pass
                        
                        chapter_data["contents"].append({
                            "name": row.name,
                            "content_type": row.content_type,
                            "content_data": row.content_data or "",
                            "order": row.order,
                            "content_reference": row.content_reference or "",
                            "actual_content": actual_content
                        })
                    lesson_data["chapters"].append(chapter_data)
                except Exception:
                    pass
            snapshot["lessons"].append(lesson_data)
        except Exception:
            pass

    return snapshot


def _apply_content_snapshot(module_id, snapshot):
    """
    Applies a content snapshot to restore the module's content to a previous state.
    Updates lesson/chapter/content records in-place using the stored snapshot.
    """
    # Restore module-level settings
    module_settings = snapshot.get("module_settings", {})
    if module_settings:
        module = frappe.get_doc("LMS Module", module_id)
        for field, value in module_settings.items():
            if module.meta.has_field(field):
                setattr(module, field, value)
        module.save(ignore_permissions=True)

    # Restore lessons, chapters, and content blocks
    for lesson_data in snapshot.get("lessons", []):
        lesson_name = lesson_data.get("name")
        if not lesson_name or not frappe.db.exists("LMS Lesson", lesson_name):
            continue
        try:
            lesson = frappe.get_doc("LMS Lesson", lesson_name)
            lesson.lesson_name = lesson_data.get("lesson_name", lesson.lesson_name)
            lesson.description = lesson_data.get("description", lesson.description or "")
            lesson.save(ignore_permissions=True)
        except Exception:
            pass

        for chapter_data in lesson_data.get("chapters", []):
            chapter_name = chapter_data.get("name")
            if not chapter_name or not frappe.db.exists("LMS Chapter", chapter_name):
                continue
            try:
                chapter = frappe.get_doc("LMS Chapter", chapter_name)
                chapter.title = chapter_data.get("title", chapter.title)

                # Build a map of existing content rows by name
                existing_map = {row.name: row for row in chapter.get("contents", [])}
                snapshot_names = {c["name"] for c in chapter_data.get("contents", []) if c.get("name")}

                # Remove rows that don't exist in the snapshot
                chapter.set("contents", [row for row in chapter.get("contents", []) if row.name in snapshot_names])

                # Update or append each content block from the snapshot
                for content_row in chapter_data.get("contents", []):
                    row_name = content_row.get("name")
                    if row_name and row_name in existing_map:
                        # Update existing row
                        for existing in chapter.get("contents", []):
                            if existing.name == row_name:
                                existing.content_type = content_row.get("content_type", existing.content_type)
                                existing.content_data = content_row.get("content_data", "")
                                existing.order = content_row.get("order", existing.order)
                                existing.content_reference = content_row.get("content_reference", "")
                                break
                    else:
                        # Append missing row
                        chapter.append("contents", {
                            "content_type": content_row.get("content_type"),
                            "content_data": content_row.get("content_data", ""),
                            "order": content_row.get("order", 0),
                            "content_reference": content_row.get("content_reference", "")
                        })

                    # Restore the actual content document (e.g., LMS Text Content)
                    actual_content = content_row.get("actual_content")
                    c_type = content_row.get("content_type")
                    c_ref = content_row.get("content_reference")
                    if actual_content and c_type and c_ref and frappe.db.exists(c_type, c_ref):
                        try:
                            c_doc = frappe.get_doc(c_type, c_ref)
                            for k, v in actual_content.items():
                                if c_doc.meta.has_field(k):
                                    setattr(c_doc, k, v)
                            c_doc.save(ignore_permissions=True)
                        except Exception:
                            pass

                chapter.save(ignore_permissions=True)
            except Exception as e:
                frappe.log_error(f"Failed to restore chapter {chapter_name}: {str(e)}")

    frappe.db.commit()



@frappe.whitelist(allow_guest=False)
def create_module_version(module_id, description=""):
    """
    Creates a new version in the module's version history.
    Takes a full JSON snapshot of all content so it can be restored later.
    """
    module = frappe.get_doc("LMS Module", module_id)
    
    # Reset is_current on all existing versions
    version_history = module.get("version_history", [])
    for v in version_history:
        v.is_current = 0
        
    # Find the true highest version by scanning ALL rows (not just last by index)
    if not version_history:
        new_version = "v1.0"
    else:
        max_major = 1
        max_minor = -1
        for v in version_history:
            try:
                ver_str = str(v.version).lstrip('vV')
                parts = ver_str.split('.')
                if len(parts) == 2:
                    major, minor = int(parts[0]), int(parts[1])
                    if (major, minor) > (max_major, max_minor):
                        max_major, max_minor = major, minor
                else:
                    major = int(float(ver_str))
                    if (major, 0) > (max_major, max_minor):
                        max_major, max_minor = major, 0
            except Exception:
                continue
        
        if max_minor == -1:
            new_version = "v1.0"
        else:
            new_version = f"v{max_major}.{max_minor + 1}"

    # Ensure no duplicate version number (safety check)
    existing_versions = {str(v.version) for v in version_history}
    while new_version in existing_versions:
        try:
            parts = new_version.lstrip('vV').split('.')
            new_version = f"v{parts[0]}.{int(parts[1]) + 1}"
        except Exception:
            new_version = f"v{len(version_history) + 1}.0"
            break

    # Build full content snapshot
    snapshot_json = json.dumps(_build_content_snapshot(module), default=str)

    module.append("version_history", {
        "version": new_version,
        "is_current": 1,
        "description": description,
        "date": today(),
        "author": frappe.session.user
    })
    
    module.save(ignore_permissions=True)

    # Frappe ORM does not reliably persist Long Text fields on child tables
    # through the parent save(). Write the snapshot directly via SQL after save.
    new_row = next(
        (v for v in module.get("version_history", []) if v.version == new_version),
        None
    )
    if new_row:
        frappe.db.set_value(
            "LMS Module Version",
            new_row.name,
            "content_snapshot",
            snapshot_json,
            update_modified=False
        )
        frappe.db.commit()

    return {"message": "success", "new_version": new_version}


@frappe.whitelist(allow_guest=False)
def restore_module_version(module_id, version):
    """
    Restores an older version by applying its saved content snapshot,
    then sets it as is_current=1.
    """
    if not frappe.has_permission("LMS Module", "write", doc=module_id):
        frappe.throw("Not permitted", frappe.PermissionError)

    module = frappe.get_doc("LMS Module", module_id)
    version_history = module.get("version_history", [])
    
    target_v = next((v for v in version_history if v.version == version), None)
    if not target_v:
        frappe.throw(f"Version {version} not found in history.")

    # Apply content snapshot if available
    if target_v.content_snapshot:
        try:
            snapshot = json.loads(target_v.content_snapshot)
            _apply_content_snapshot(module_id, snapshot)
        except Exception as e:
            frappe.log_error(f"Failed to restore snapshot for version {version}: {str(e)}")
            frappe.throw(f"Failed to restore content: {str(e)}")

    # Reload module after snapshot apply (save may have happened inside)
    module = frappe.get_doc("LMS Module", module_id)
    version_history = module.get("version_history", [])
    target_v = next((v for v in version_history if v.version == version), None)
    
    for v in version_history:
        v.is_current = 1 if (target_v and v.name == target_v.name) else 0
        
    module.save(ignore_permissions=True)
    return {"message": "success", "restored_version": version}


@frappe.whitelist(allow_guest=False)
def has_unpublished_changes(module_id):
    """
    Checks if the module, any of its lessons, any of its chapters,
    or any content blocks inside those chapters have been modified
    since the latest published version.

    Doctypes checked:
      1. LMS Module          - module settings, title, description etc.
      2. LMS Lesson          - lesson title, order, estimated time etc.
      3. LMS Chapter         - chapter title, order etc.
      4. LMS Chapter Content - actual text, video, audio, quiz content blocks

    Uses `creation` (not `modified`) of the version history row as the publish
    baseline, because `modified` gets re-stamped every time the parent module
    is saved, making it unreliable as a change-detection anchor.
    """
    module = frappe.get_doc("LMS Module", module_id)

    versions = module.get("version_history", [])
    if not versions:
        # Never published — always treat as having unpublished changes
        return {"has_changes": True}

    # Use the current version's CREATION time as the publish baseline.
    # `creation` is set once when the row is inserted and never changes.
    latest_v = next((v for v in versions if v.is_current), versions[-1])
    version_time = latest_v.creation

    if version_time is None:
        return {"has_changes": True}

    # 1. LMS Module
    if module.modified > version_time:
        return {"has_changes": True}

    # Collect lesson names
    lesson_names = [l.lesson for l in module.get("lessons", []) if l.lesson]
    if not lesson_names:
        return {"has_changes": False}

    # 2. LMS Lesson
    lessons = frappe.db.get_all(
        "LMS Lesson",
        filters={"name": ["in", lesson_names]},
        fields=["modified"]
    )
    for lesson in lessons:
        if lesson.modified > version_time:
            return {"has_changes": True}

    # Collect chapter names
    chapter_links = frappe.db.get_all(
        "LMS Lesson Chapter",
        filters={"parent": ["in", lesson_names]},
        fields=["chapter"]
    )
    chapter_names = [c.chapter for c in chapter_links if c.chapter]
    if not chapter_names:
        return {"has_changes": False}

    # 3. LMS Chapter
    chapters = frappe.db.get_all(
        "LMS Chapter",
        filters={"name": ["in", chapter_names]},
        fields=["modified"]
    )
    for chapter in chapters:
        if chapter.modified > version_time:
            return {"has_changes": True}

    # 4. LMS Chapter Content (text, video, audio, quiz, etc.)
    content_blocks = frappe.db.get_all(
        "LMS Chapter Content",
        filters={"parent": ["in", chapter_names], "parenttype": "LMS Chapter"},
        fields=["modified", "content_type", "content_reference"]
    )
    for block in content_blocks:
        if block.modified > version_time:
            return {"has_changes": True}
            
        # Check the actual content document
        if block.content_type and block.content_reference:
            try:
                content_modified = frappe.db.get_value(block.content_type, block.content_reference, "modified")
                if content_modified and content_modified > version_time:
                    return {"has_changes": True}
            except Exception:
                pass

    return {"has_changes": False}
