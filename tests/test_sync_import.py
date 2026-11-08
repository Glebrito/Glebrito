import json
import unittest
from pathlib import Path

from colih_hourglass.schedule_parse import parse_all_assignments, parse_sex_from_users, parse_users
from colih_hourglass.sync import (
    _looks_like_placeholder,
    infer_sex_from_assignments,
    members_from_privileges,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_users_payload.json"


class TestParseUsersFixture(unittest.TestCase):
    def test_parse_users_from_startup_shape(self) -> None:
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        names = parse_users(payload)
        self.assertIn("3035569", names)
        self.assertIn("Maria", names["3035569"])


class TestInferSex(unittest.TestCase):
    def test_apply_slots_infer_female(self) -> None:
        rows = [
            ("2026-01-05", "apply1", 101, "Ana"),
            ("2026-01-05", "chairman", 202, "João"),
            ("2026-01-12", "apply2_assistant", 303, None),
        ]
        sex = infer_sex_from_assignments(rows)
        self.assertEqual(sex.get(101), "Female")
        self.assertEqual(sex.get(303), "Female")
        self.assertNotIn(202, sex)


class TestBrowserExportUsersObject(unittest.TestCase):
    def test_display_names_from_users_not_id_prefix(self) -> None:
        users = json.loads(FIXTURE.read_text(encoding="utf-8"))
        priv = {"chairman": [3035569], "apply1": [3035547]}
        names = parse_users(users)
        sex = parse_sex_from_users(users)
        rows = members_from_privileges(
            "cong-test",
            priv,
            user_names=names,
            sex_by_id=sex,
        )
        by_id = {r["hourglass_user_id"]: r for r in rows}
        self.assertFalse(_looks_like_placeholder(by_id[3035569]["display_name"]))
        self.assertIn("Maria", by_id[3035569]["display_name"])
        self.assertEqual(by_id[3035569]["sex"], "Female")
        self.assertFalse(_looks_like_placeholder(by_id[3035547]["display_name"]))

    def test_schedule_assignments_use_users_directory(self) -> None:
        users = json.loads(FIXTURE.read_text(encoding="utf-8"))
        schedules = [
            {
                "date": "2026-01-05",
                "fm": [{"assignee": 3035569}, {"assignee": 3035547}],
            }
        ]
        _rows, id_names = parse_all_assignments(schedules)
        for uid, label in parse_users(users).items():
            id_names[uid] = label
        self.assertFalse(_looks_like_placeholder(id_names.get("3035569")))


class TestMembersFromPrivilegeDict(unittest.TestCase):
    def test_hourglass_privilege_map_ids(self) -> None:
        priv = {
            "apply1": [101, 202],
            "chairman": [303],
        }
        user_names = {"101": "Ana Silva", "303": "Pedro"}
        rows = members_from_privileges(
            "cong-test",
            priv,
            user_names=user_names,
            sex_by_id={101: "Female"},
        )
        by_id = {r["hourglass_user_id"]: r for r in rows}
        self.assertEqual(by_id[101]["display_name"], "Ana Silva")
        self.assertEqual(by_id[101]["sex"], "Female")
        self.assertIn("apply1", by_id[101]["privileges"])
        self.assertEqual(by_id[303]["display_name"], "Pedro")


if __name__ == "__main__":
    unittest.main()
