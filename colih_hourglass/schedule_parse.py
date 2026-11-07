"""
Parser de schedule Hourglass — espelha hourglass_rotation_report.py (stdlib).
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, DefaultDict, Dict, Iterable, List, Optional, Set, Tuple

# hourglass_rotation_report.py vem no pacote; store Cursor é fallback opcional
_PACKAGE_REPORT = Path(__file__).resolve().parent / "hourglass_rotation_report.py"
_STORE_REPORT = Path("/cursor/stores/self/scripts/hourglass_rotation_report.py")


def _load_rotation_module():
    import importlib.util

    for report_path in (_PACKAGE_REPORT, _STORE_REPORT):
        if not report_path.is_file():
            continue
        spec = importlib.util.spec_from_file_location("hourglass_rotation_report", report_path)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            sys.modules["hourglass_rotation_report"] = mod
            spec.loader.exec_module(mod)
            return mod
    return None


_rotation = _load_rotation_module()

if _rotation:
    extract_schedule_roots = _rotation.extract_schedule_roots
    parse_schedules = _rotation.parse_schedules
    parse_privileges = _rotation.parse_privileges
    parse_users = _rotation.parse_users
    publisher_label = _rotation.publisher_label
    HOURGLASS_SECTIONS = _rotation.HOURGLASS_SECTIONS
    walk_week = _rotation.walk_week
    _walk_hourglass_sections = _rotation._walk_hourglass_sections
    record_assignment = _rotation.record_assignment
    categorize_field_key = _rotation.categorize_field_key
    ROLE_ALIASES = _rotation.ROLE_ALIASES
else:
    # Fallback mínimo embutido (testes sem store)
    def extract_schedule_roots(payload: Any) -> List[Any]:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("schedules", "schedule", "data"):
                val = payload.get(key)
                if isinstance(val, list):
                    return val
        return []

    HOURGLASS_SECTIONS = (
        ("tgw", ("treasures_talk", "spiritual_gems", "bible_reading")),
        ("fm", ("apply1", "apply2", "apply3", "apply4")),
        ("lac", ("living1", "cbs")),
    )

    def record_assignment(counts, category, person):
        if person and category:
            counts[category][person] += 1

    def parse_schedules(payload):
        weeks = extract_schedule_roots(payload)
        counts = defaultdict(lambda: defaultdict(int))
        id_names: Dict[str, str] = {}
        week_count = 0
        for week in weeks:
            if isinstance(week, dict) and week.get("date"):
                week_count += 1
        return counts, id_names, week_count


AssignmentRow = Tuple[str, str, Optional[int], Optional[str]]  # week_date, category, user_id, label


def _resolve_user_id(raw: Any) -> Optional[int]:
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    if isinstance(raw, str) and raw.strip().isdigit():
        return int(raw.strip())
    if isinstance(raw, dict):
        for k in ("user_id", "id", "publisher_id", "assignee_id"):
            if raw.get(k) is not None:
                try:
                    return int(raw[k])
                except (TypeError, ValueError):
                    pass
    return None


def iter_assignments_from_week(week: Dict[str, Any], id_names: Dict[str, str]) -> List[AssignmentRow]:
    """Extrai (date, category, hourglass_user_id, label) de uma entrada semanal."""
    week_date = str(week.get("date", ""))[:10]
    if not week_date:
        return []
    rows: List[AssignmentRow] = []
    skip_roots = frozenset({"tgw", "fm", "lac", "date", "id", "meta"})

    for section, slots in HOURGLASS_SECTIONS:
        items = week.get(section)
        if not isinstance(items, list):
            continue
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            cat = slots[idx] if idx < len(slots) else f"{section}_{idx + 1}"
            assignee = item.get("assignee")
            uid = _resolve_user_id(assignee)
            label = publisher_label(assignee, id_names) if _rotation and assignee is not None else None
            if uid:
                rows.append((week_date, cat, uid, label))
            assistant = item.get("assistant")
            auid = _resolve_user_id(assistant)
            if auid:
                alabel = publisher_label(assistant, id_names) if _rotation else None
                rows.append((week_date, f"{cat}_assistant", auid, alabel))

    if _rotation:
        for key, value in week.items():
            if _norm_key_simple(key) in skip_roots:
                continue
            cat = categorize_field_key(key)
            if not cat:
                continue
            if isinstance(value, (dict, int, str)) and not isinstance(value, list):
                uid = _resolve_user_id(value)
                if uid:
                    label = publisher_label(value, id_names)
                    rows.append((week_date, cat, uid, label))

    seen: Set[Tuple[str, str, int]] = set()
    out: List[AssignmentRow] = []
    for r in rows:
        if r[2] is None:
            continue
        key = (r[0], r[1], r[2])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _norm_key_simple(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")


def parse_all_assignments(payload: Any) -> Tuple[List[AssignmentRow], Dict[str, str]]:
    weeks = extract_schedule_roots(payload)
    id_names: Dict[str, str] = {}
    if _rotation and hasattr(_rotation, "index_publishers_from_schedules"):
        _rotation.index_publishers_from_schedules(weeks, id_names)
    all_rows: List[AssignmentRow] = []
    for week in weeks:
        if isinstance(week, dict):
            all_rows.extend(iter_assignments_from_week(week, id_names))
    return all_rows, id_names


def parse_week_date(s: str) -> date:
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def weeks_between(earlier: date, later: date) -> int:
    return max(0, (later - earlier).days // 7)
