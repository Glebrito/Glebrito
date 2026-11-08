import unittest
from datetime import date

from colih_hourglass.rules_engine import (
    Member,
    RulesConfig,
    SpacingConfig,
    build_history_index,
    eligible_for_category,
    is_sister,
    suggest_week,
    spacing_ok,
)


def m(mid: str, uid: int, name: str, sex: str | None) -> Member:
    return Member(id=mid, hourglass_user_id=uid, display_name=name, sex=sex)


class TestSisterRules(unittest.TestCase):
    def test_sisters_only_apply_slots(self):
        rules = RulesConfig()
        brothers = [m("b1", 1, "João", "Male"), m("b2", 2, "Pedro", "Male")]
        sisters = [m("s1", 3, "Maria", "Female"), m("s2", 4, "Ana", "Female")]
        pool = eligible_for_category(brothers + sisters, "apply1", None, rules)
        self.assertTrue(all(is_sister(x) for x in pool))
        self.assertEqual({x.display_name for x in pool}, {"Maria", "Ana"})

    def test_brother_allowed_apply4(self):
        rules = RulesConfig()
        members = [m("b1", 1, "João", "Male"), m("s1", 3, "Maria", "Female")]
        pool = eligible_for_category(members, "apply4", None, rules)
        self.assertEqual(len(pool), 2)


class TestSpacing(unittest.TestCase):
    def test_same_role_spacing_blocks(self):
        rules = RulesConfig(spacing=SpacingConfig(same_role_min_weeks=3, sister_fm_min_weeks=3))
        member = m("s1", 10, "Maria", "Female")
        last_role = {10: {"apply1": date(2026, 10, 5)}}
        ok, reason = spacing_ok(
            member,
            "apply1",
            date(2026, 10, 19),
            last_role,
            {},
            rules,
        )
        self.assertFalse(ok)
        self.assertIn("espaçamento", reason)

    def test_spacing_allows_after_min_weeks(self):
        rules = RulesConfig(spacing=SpacingConfig(same_role_min_weeks=2))
        member = m("s1", 10, "Maria", "Female")
        last_role = {10: {"chairman": date(2026, 10, 5)}}
        ok, _ = spacing_ok(member, "chairman", date(2026, 10, 19), last_role, {}, rules)
        self.assertTrue(ok)


class TestFairRotation(unittest.TestCase):
    def test_picks_lowest_count(self):
        rules = RulesConfig()
        members = [
            m("a", 1, "Alice", "Female"),
            m("b", 2, "Beatriz", "Female"),
        ]
        history = [
            {
                "member_id": "a",
                "hourglass_user_id": 1,
                "week_date": "2026-09-01",
                "role_category": "apply1",
            },
            {
                "member_id": "a",
                "hourglass_user_id": 1,
                "week_date": "2026-09-08",
                "role_category": "apply1",
            },
        ]
        suggestions = suggest_week(
            target_week=date(2026, 10, 26),
            members=members,
            history=history,
            rules=rules,
            eligible_by_category={},
            categories=["apply1"],
        )
        self.assertEqual(suggestions[0]["member_id"], "b")

    def test_no_duplicate_same_week_student_assistant(self):
        rules = RulesConfig()
        members = [
            m("a", 1, "Alice", "Female"),
            m("b", 2, "Beatriz", "Female"),
        ]
        suggestions = suggest_week(
            target_week=date(2026, 10, 26),
            members=members,
            history=[],
            rules=rules,
            eligible_by_category={},
            categories=["apply1", "apply1_assistant"],
        )
        ids = [s["member_id"] for s in suggestions if s.get("member_id")]
        self.assertEqual(len(ids), len(set(ids)))


class TestHistoryIndex(unittest.TestCase):
    def test_counts_per_category(self):
        history = [
            {"member_id": "x", "hourglass_user_id": 5, "week_date": "2026-01-01", "role_category": "chairman"},
            {"member_id": "x", "hourglass_user_id": 5, "week_date": "2026-01-08", "role_category": "chairman"},
        ]
        counts, _, _ = build_history_index(history)
        self.assertEqual(counts["chairman"]["x"], 2)


if __name__ == "__main__":
    unittest.main()
