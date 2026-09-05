import frappe
from frappe.utils import today, add_days, getdate, date_diff

class BadgeEvaluator:
    def __init__(self, user, earned_map, deps_map):
        self.user = user
        self.earned_map = earned_map
        self.deps_map = deps_map
        
    def evaluate(self, badge):
        name = badge.badge_name
        
        # Check dynamic dependencies from the required_badges child table
        required_badges = self.deps_map.get(name, [])
        for req_badge in required_badges:
            if req_badge not in self.earned_map:
                return 0.0, f"Earn {req_badge} first"
        
        if name == "Learning Champion":
            return self.eval_learning_champion(badge)
            
        elif name == "Ahead of the Curve":
            return self.eval_ahead_of_curve(badge)
            
        elif name == "Consistency Pro":
            return self.eval_consistency_pro(badge)
            
        elif name == "Top Performer":
            return self.eval_top_performer(badge)
            
        elif name in ("Top Knowledge Seeker", "Knowledge Seeker"):
            return self.eval_knowledge_seeker(badge)
            
        elif name == "Learning Elite":
            return self.eval_learning_elite(badge)
            
        return 0.0, "0%"

    def eval_learning_champion(self, badge):
        # 90%+ of assigned modules before deadlines for 2 consecutive months.
        # We approximate this by checking the last 2 months of completed mandatory modules.
        query = """
            SELECT count(ma.module)
            FROM `tabLMS Assignment User` au
            JOIN `tabLMS Module Assignment` ma ON ma.name = au.parent
            WHERE au.user = %s AND ma.is_mandatory = 1
            AND DATE_ADD(ma.creation, INTERVAL ma.duration DAY) >= DATE_SUB(CURDATE(), INTERVAL 60 DAY)
        """
        total_due = frappe.db.sql(query, self.user)[0][0] or 0
        if total_due == 0:
            return 0.0, "0/0 on-time"
        
        query_completed = """
            SELECT count(DISTINCT tr.module)
            FROM `tabLMS Module Tracker` tr
            JOIN `tabLMS Assignment User` au ON au.user = tr.user
            JOIN `tabLMS Module Assignment` ma ON ma.name = au.parent AND ma.module = tr.module
            WHERE tr.user = %s AND tr.status = 'Completed' AND ma.is_mandatory = 1
            AND DATE_ADD(ma.creation, INTERVAL ma.duration DAY) >= DATE_SUB(CURDATE(), INTERVAL 60 DAY)
            AND tr.completed_on <= DATE_ADD(ma.creation, INTERVAL ma.duration DAY)
        """
        completed = frappe.db.sql(query_completed, self.user)[0][0] or 0
        ratio = (completed / total_due) * 100
        progress = min((ratio / 90.0) * 100, 100) if ratio > 0 else 0
        return progress, f"{int(ratio)}% on-time (2mo)"

    def eval_ahead_of_curve(self, badge):
        # Completed 5 assigned modules at least 2 days before deadlines.
        target = badge.target_count or 5
        query = """
            SELECT count(DISTINCT tr.module)
            FROM `tabLMS Module Tracker` tr
            JOIN `tabLMS Assignment User` au ON au.user = tr.user
            JOIN `tabLMS Module Assignment` ma ON ma.name = au.parent AND ma.module = tr.module
            WHERE tr.user = %s AND tr.status = 'Completed' AND ma.is_mandatory = 1
            AND tr.completed_on <= DATE_SUB(DATE_ADD(ma.creation, INTERVAL ma.duration DAY), INTERVAL 2 DAY)
        """
        count = frappe.db.sql(query, self.user)[0][0] or 0
        progress = min((count / target) * 100, 100)
        return progress, f"{count}/{target} early"

    def eval_consistency_pro(self, badge):
        # Completed learning activities for 30 consecutive days.
        # We query for 30 distinct days of activity within the last 30 days.
        target = badge.target_count or 30
        query = """
            SELECT COUNT(DISTINCT DATE(modified))
            FROM `tabLMS Module Tracker`
            WHERE user = %s AND modified >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
        """
        count = frappe.db.sql(query, (self.user, target))[0][0] or 0
        progress = min((count / target) * 100, 100)
        return progress, f"{count}/{target} days"

    def eval_top_performer(self, badge):
        # Average assessment score of 90%+ across 5 modules.
        target_count = badge.target_count or 5
        min_score = badge.minimum_score or 90
        
        query = """
            SELECT total_score
            FROM `tabLMS Module Tracker`
            WHERE user = %s AND status = 'Completed' AND total_score > 0
            ORDER BY completed_on DESC
            LIMIT %s
        """
        scores = frappe.db.sql(query, (self.user, target_count))
        if not scores:
            return 0.0, "0/0 avg"
        
        avg_score = sum(s[0] for s in scores) / len(scores)
        progress = min((avg_score / min_score) * 100, 100)
        return progress, f"{int(avg_score)}% avg score"

    def eval_knowledge_seeker(self, badge):
        # 5 optional modules completed
        target = badge.target_count or 5
        query = """
            SELECT count(DISTINCT tr.module)
            FROM `tabLMS Module Tracker` tr
            WHERE tr.user = %s AND tr.status = 'Completed'
            AND NOT EXISTS (
                SELECT 1 
                FROM `tabLMS Assignment User` au 
                JOIN `tabLMS Module Assignment` ma ON ma.name = au.parent
                WHERE ma.module = tr.module AND au.user = tr.user AND ma.is_mandatory = 1
            )
        """
        count = frappe.db.sql(query, self.user)[0][0] or 0
        progress = min((count / target) * 100, 100)
        return progress, f"{count}/{target} optional"

    def eval_learning_elite(self, badge):
        # 95%+ on-time completion, 90%+ assessment average, and consistent learning activity over 3 months.
        
        # 1. On-time completion (last 3 months)
        query_due = """
            SELECT count(ma.module)
            FROM `tabLMS Module Assignment` ma JOIN `tabLMS Assignment User` au ON ma.name = au.parent
            WHERE au.user = %s AND ma.is_mandatory = 1 AND DATE_ADD(ma.creation, INTERVAL ma.duration DAY) >= DATE_SUB(CURDATE(), INTERVAL 90 DAY)
        """
        total_due = frappe.db.sql(query_due, self.user)[0][0] or 0
        if total_due > 0:
            query_completed = """
                SELECT count(DISTINCT tr.module)
                FROM `tabLMS Module Tracker` tr JOIN `tabLMS Assignment User` au ON tr.user = au.user
                JOIN `tabLMS Module Assignment` ma ON ma.name = au.parent AND ma.module = tr.module
                WHERE tr.user = %s AND tr.status = 'Completed' AND ma.is_mandatory = 1
                AND DATE_ADD(ma.creation, INTERVAL ma.duration DAY) >= DATE_SUB(CURDATE(), INTERVAL 90 DAY) AND tr.completed_on <= DATE_ADD(ma.creation, INTERVAL ma.duration DAY)
            """
            completed = frappe.db.sql(query_completed, self.user)[0][0] or 0
            on_time_pct = (completed / total_due) * 100
        else:
            on_time_pct = 0
            
        # 2. Assessment average
        query_score = "SELECT AVG(total_score) FROM `tabLMS Module Tracker` WHERE user = %s AND status = 'Completed' AND total_score > 0"
        avg_score = frappe.db.sql(query_score, self.user)[0][0] or 0
        
        # 3. 3 months consistency (e.g. 90 days of activity)
        query_days = "SELECT COUNT(DISTINCT DATE(modified)) FROM `tabLMS Module Tracker` WHERE user = %s AND modified >= DATE_SUB(CURDATE(), INTERVAL 90 DAY)"
        active_days = frappe.db.sql(query_days, self.user)[0][0] or 0
        
        # Evaluate Progress Multipliers
        p1 = min((on_time_pct / 95.0) * 100, 100)
        p2 = min((avg_score / 90.0) * 100, 100)
        p3 = min((active_days / 90.0) * 100, 100)
        
        total_progress = (p1 + p2 + p3) / 3
        return total_progress, "Elite Status"

@frappe.whitelist()
def get_learner_badges(user_id=None):
    """Returns badges earned by the current learner, and badges in progress, evaluating dynamically."""
    if user_id and user_id != frappe.session.user:
        roles = frappe.get_roles(frappe.session.user)
        if not any(r in roles for r in ["System Manager", "Administrator", "LMS Administrator"]):
            frappe.throw("Not permitted to view other user's badges", frappe.PermissionError)
            
    user = user_id or frappe.session.user

    earned_badges = frappe.get_all(
        "LMS Learner Badge",
        filters={"user": user},
        fields=["badge", "awarded_on"],
        order_by="awarded_on desc"
    )
    earned_map = {b.badge: b.awarded_on for b in earned_badges}

    # Fetch badges dynamically using only hardcoded fields
    all_badges = frappe.get_all(
        "LMS Badge",
        filters={"is_active": 1},
        fields=["name", "badge_name", "description", "achievement_criteria", "badge_image as image", "minimum_score", "target_count"]
    )
    
    # Fetch dependencies dynamically
    badge_dependencies = frappe.get_all(
        "LMS Badge Dependency",
        fields=["parent", "badge"]
    )
    deps_map = {}
    for d in badge_dependencies:
        deps_map.setdefault(d.parent, []).append(d.badge)
    
    # Fetch recently completed modules for 'Related Learning'
    recently_completed = frappe.get_all(
        "LMS Module Tracker",
        filters={"user": user, "status": "Completed"},
        fields=["module"],
        order_by="modified desc",
        limit=2
    )
    related_learning = []
    for t in recently_completed:
        title = frappe.get_value("LMS Module", t.module, "module_name")
        if title:
            related_learning.append({"title": title, "progress": 100})

    evaluator = BadgeEvaluator(user, earned_map, deps_map)
    results = []
    newly_awarded = []

    for b in all_badges:
        earned_on = earned_map.get(b.name)
        if earned_on:
            results.append({
                "id": b.name,
                "title": b.badge_name,
                "description": b.description or "",
                "achievementCriteria": b.achievement_criteria or "",
                "image": b.image,
                "earned": True,
                "earnedOn": str(earned_on),
                "relatedLearning": related_learning
            })
        else:
            progress, label = evaluator.evaluate(b)
            progress = int(round(progress))
            if progress >= 100:
                doc = frappe.get_doc({
                    "doctype": "LMS Learner Badge",
                    "user": user,
                    "badge": b.name,
                    "awarded_on": today()
                })
                doc.insert(ignore_permissions=True)
                newly_awarded.append(doc)
                earned_map[b.name] = doc.awarded_on
                
                results.append({
                    "id": b.name,
                    "title": b.badge_name,
                    "description": b.description or "",
                    "achievementCriteria": b.achievement_criteria or "",
                    "image": b.image,
                    "earned": True,
                    "earnedOn": str(doc.awarded_on),
                    "relatedLearning": related_learning
                })
            else:
                results.append({
                    "id": b.name,
                    "title": b.badge_name,
                    "description": b.description or "",
                    "achievementCriteria": b.achievement_criteria or "",
                    "image": b.image,
                    "earned": False,
                    "progress": progress,
                    "progressLabel": label,
                    "relatedLearning": related_learning
                })

    if newly_awarded:
        frappe.db.commit()

    earned_list = sorted([r for r in results if r["earned"]], key=lambda x: x["earnedOn"], reverse=True)
    in_progress_list = sorted([r for r in results if not r["earned"]], key=lambda x: x["progress"], reverse=True)
    
    return earned_list + in_progress_list
