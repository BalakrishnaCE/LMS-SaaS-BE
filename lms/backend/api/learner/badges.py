import frappe

@frappe.whitelist()
def get_learner_badges():
    """Returns badges earned by the current learner, and badges in progress."""
    user = frappe.session.user

    # Get earned badges
    earned_badges = frappe.get_all(
        "LMS Learner Badge",
        filters={"user": user},
        fields=["badge", "awarded_on"],
        order_by="awarded_on desc"
    )
    earned_map = {b.badge: b.awarded_on for b in earned_badges}

    # Get all active badges
    all_badges = frappe.get_all(
        "LMS Badge",
        filters={"is_active": 1},
        fields=["name", "badge_name", "description", "badge_image as image", "criteria_type", "module", "minimum_score"]
    )

    results = []
    
    # We will fetch module trackers for "in progress" badges
    modules_to_check = [b.module for b in all_badges if b.module and b.name not in earned_map]
    trackers = {}
    if modules_to_check:
        tracker_docs = frappe.get_all(
            "LMS Module Tracker",
            filters={"user": user, "module": ["in", modules_to_check], "status": "In Progress"},
            fields=["module", "progress_percentage"]
        )
        trackers = {t.module: (t.progress_percentage or 0) for t in tracker_docs}

    for b in all_badges:
        earned_on = earned_map.get(b.name)
        
        # Map badge image to corresponding style ID
        style_id = "ach-1"
        if "crown" in (b.image or ""):
            style_id = "ach-2"
        elif "trophy" in (b.image or ""):
            style_id = "ach-3"

        if earned_on:
            results.append({
                "id": style_id, # Use style_id instead of random UUID for styling
                "title": b.badge_name,
                "description": b.description or "",
                "image": b.image,
                "earned": True,
                "earnedOn": str(earned_on)
            })
        else:
            # Check if in progress
            if b.module and b.module in trackers:
                progress = trackers[b.module]
                results.append({
                    "id": style_id,
                    "title": b.badge_name,
                    "description": b.description or "",
                    "image": b.image,
                    "earned": False,
                    "progress": progress,
                    "progressLabel": f"{int(progress)}% completed"
                })

    # Sort: Earned first (by newest), then in-progress by progress desc
    def sort_key(x):
        if x.get("earned"):
            # (earned_group, date_str, tie_breaker)
            # using "" date is fine since earned ones will have a date string
            # wait, date desc means we should use negative timestamps, or just sort them after
            # Python's default string sort is asc, so we might need reverse=True for dates
            # Actually let's just return a generic tuple and we'll sort earned separately
            pass
        return x

    earned_list = sorted([r for r in results if r["earned"]], key=lambda x: x["earnedOn"], reverse=True)
    in_progress_list = sorted([r for r in results if not r["earned"]], key=lambda x: x["progress"], reverse=True)
    
    return earned_list + in_progress_list
