import unittest

from colih_hourglass.cli import _eligible_map_from_members
from colih_hourglass.rules_engine import Member, RulesConfig, eligible_for_category


def _member(uid: int, privs: set[str]) -> Member:
    return Member(
        id=f"m-{uid}",
        hourglass_user_id=uid,
        display_name=f"User {uid}",
        sex="Male",
        privileges=privs,
    )


class TestEligibleMapFromMembers(unittest.TestCase):
    def test_prayer_privilege_maps_to_opening_and_closing(self):
        members = [
            _member(100, {"prayer"}),
            _member(200, {"chairman"}),
        ]
        eligible = _eligible_map_from_members(members)
        self.assertIn("100", eligible.get("opening_prayer", set()))
        self.assertIn("100", eligible.get("closing_prayer", set()))
        self.assertNotIn("100", eligible.get("chairman", set()))
        self.assertIn("200", eligible.get("chairman", set()))

    def test_hourglass_category_key_on_member(self):
        members = [_member(42, {"openingPrayer"})]
        eligible = _eligible_map_from_members(members)
        self.assertEqual(eligible.get("opening_prayer"), {"42"})


class TestEligibleForCategoryEmptySet(unittest.TestCase):
    def test_empty_eligible_set_excludes_all(self):
        rules = RulesConfig()
        members = [
            Member(id="a", hourglass_user_id=1, display_name="A", sex="Male"),
            Member(id="b", hourglass_user_id=2, display_name="B", sex="Male"),
        ]
        pool = eligible_for_category(members, "opening_prayer", set(), rules)
        self.assertEqual(pool, [])

    def test_none_eligible_allows_all_after_other_filters(self):
        rules = RulesConfig()
        members = [
            Member(id="a", hourglass_user_id=1, display_name="A", sex="Male"),
        ]
        pool = eligible_for_category(members, "chairman", None, rules)
        self.assertEqual(len(pool), 1)


if __name__ == "__main__":
    unittest.main()
