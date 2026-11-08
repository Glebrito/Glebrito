from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Set, Tuple

from .schedule_parse import parse_week_date, weeks_between

# Categorias sugeridas por ordem de preenchimento típica
SUGGESTION_ORDER = [
    "chairman",
    "opening_prayer",
    "closing_prayer",
    "treasures_talk",
    "spiritual_gems",
    "bible_reading",
    "apply1",
    "apply1_assistant",
    "apply2",
    "apply2_assistant",
    "apply3",
    "apply3_assistant",
    "apply4",
    "apply4_assistant",
    "living1",
    "living2",
    "living3",
    "cbs",
    "cbs_reader",
    "auxiliary_counselor",
]

SISTER_FM_CATEGORIES = frozenset(
    {
        "apply1",
        "apply2",
        "apply3",
        "apply1_assistant",
        "apply2_assistant",
        "apply3_assistant",
    }
)

FM_PAIR_PREFIXES = ("apply1", "apply2", "apply3")


@dataclass
class Member:
    id: str
    hourglass_user_id: int
    display_name: str
    sex: Optional[str]
    privileges: Set[str] = field(default_factory=set)


@dataclass
class SpacingConfig:
    same_role_min_weeks: int = 2
    sister_fm_min_weeks: int = 3


@dataclass
class RulesConfig:
    sisters_only_categories: Set[str] = field(default_factory=lambda: set(SISTER_FM_CATEGORIES))
    spacing: SpacingConfig = field(default_factory=SpacingConfig)
    hourglass_id_aliases: Dict[str, int] = field(default_factory=dict)
    category_bans_by_uid: Dict[str, List[str]] = field(default_factory=dict)
    excluded_hourglass_ids: Set[int] = field(default_factory=set)


def normalize_sex(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip().lower()
    if v in ("f", "female", "feminino", "irmã", "irma"):
        return "Female"
    if v in ("m", "male", "masculino", "irmão", "irmao"):
        return "Male"
    return value


def is_sister(member: Member) -> bool:
    return normalize_sex(member.sex) == "Female"


def load_rules_from_db(rows: List[Dict[str, Any]], spacing_rows: List[Dict[str, Any]]) -> RulesConfig:
    cfg = RulesConfig()
    for row in rows:
        key = row.get("rule_key")
        val = row.get("rule_value")
        if key == "sisters_only_categories" and isinstance(val, list):
            cfg.sisters_only_categories = set(str(x) for x in val)
        elif key == "sisters_only_categories" and isinstance(val, str):
            cfg.sisters_only_categories = set(json.loads(val))
        elif key == "hourglass_id_aliases" and isinstance(val, dict):
            cfg.hourglass_id_aliases = {str(k): int(v) for k, v in val.items()}
        elif key == "category_bans_by_uid" and isinstance(val, dict):
            cfg.category_bans_by_uid = {
                str(k): [str(c) for c in v] if isinstance(v, list) else []
                for k, v in val.items()
            }
        elif key == "excluded_hourglass_ids" and isinstance(val, list):
            cfg.excluded_hourglass_ids = {int(x) for x in val}
    for row in spacing_rows:
        if not row.get("active", True):
            continue
        kind = row.get("constraint_kind")
        weeks = int(row.get("min_weeks", 2))
        if kind == "same_role":
            cfg.spacing.same_role_min_weeks = weeks
        elif kind == "any_sister_fm":
            cfg.spacing.sister_fm_min_weeks = weeks
    return cfg


def canonical_hourglass_uid(uid: int, rules: RulesConfig) -> int:
    mapped = rules.hourglass_id_aliases.get(str(uid))
    return int(mapped) if mapped is not None else uid


def filter_members_for_rules(members: List[Member], rules: RulesConfig) -> List[Member]:
    duplicate_ids = {int(k) for k in rules.hourglass_id_aliases.keys()}
    out: List[Member] = []
    for m in members:
        if m.hourglass_user_id in rules.excluded_hourglass_ids:
            continue
        if m.hourglass_user_id in duplicate_ids:
            continue
        out.append(m)
    return out


def category_banned_for_member(member: Member, category: str, rules: RulesConfig) -> bool:
    uid = member.hourglass_user_id
    for key in (str(uid), str(canonical_hourglass_uid(uid, rules))):
        banned = rules.category_bans_by_uid.get(key)
        if banned and category in banned:
            return True
    return False


def remap_eligible_by_category(
    eligible_by_category: Dict[str, Set[str]],
    rules: RulesConfig,
) -> Dict[str, Set[str]]:
    if not rules.hourglass_id_aliases:
        return eligible_by_category
    out: Dict[str, Set[str]] = {}
    for category, ids in eligible_by_category.items():
        remapped: Set[str] = set()
        for uid_s in ids:
            if uid_s in rules.hourglass_id_aliases:
                remapped.add(str(rules.hourglass_id_aliases[uid_s]))
            else:
                remapped.add(uid_s)
        out[category] = remapped
    return out


def build_history_index(
    history: List[Dict[str, Any]],
    *,
    rules: Optional[RulesConfig] = None,
    members_by_uid: Optional[Dict[int, Member]] = None,
) -> Tuple[Dict[str, Dict[str, int]], Dict[int, Dict[str, date]], Dict[int, date]]:
    """Contagens por categoria+member_id, última data por membro+categoria, última FM irmã."""
    counts: Dict[str, Dict[str, int]] = {}
    last_role: Dict[int, Dict[str, date]] = {}
    last_sister_fm: Dict[int, date] = {}

    for row in history:
        cat = row.get("role_category") or ""
        mid = row.get("member_id")
        uid = row.get("hourglass_user_id")
        wd = row.get("week_date")
        if not cat or not wd:
            continue
        raw_uid = int(uid) if uid else None
        key_id = canonical_hourglass_uid(raw_uid, rules) if raw_uid is not None and rules else raw_uid
        count_mid: Optional[str] = str(mid) if mid else None
        if members_by_uid and key_id is not None and key_id in members_by_uid:
            count_mid = members_by_uid[key_id].id
        if count_mid:
            counts.setdefault(cat, {})
            counts[cat][count_mid] = counts[cat].get(count_mid, 0) + 1
        try:
            d = parse_week_date(str(wd))
        except ValueError:
            continue
        if key_id is not None:
            last_role.setdefault(key_id, {})
            prev = last_role[key_id].get(cat)
            if prev is None or d > prev:
                last_role[key_id][cat] = d
        if cat in SISTER_FM_CATEGORIES and key_id:
            prev = last_sister_fm.get(key_id)
            if prev is None or d > prev:
                last_sister_fm[key_id] = d
    return counts, last_role, last_sister_fm


def eligible_for_category(
    members: List[Member],
    category: str,
    eligible_ids: Optional[Set[str]],
    rules: RulesConfig,
) -> List[Member]:
    out: List[Member] = []
    for m in members:
        if not m.hourglass_user_id:
            continue
        uid = str(m.hourglass_user_id)
        if eligible_ids is not None and uid not in eligible_ids and m.id not in eligible_ids:
            continue
        if category in rules.sisters_only_categories and not is_sister(m):
            continue
        if category_banned_for_member(m, category, rules):
            continue
        out.append(m)
    return out


def spacing_ok(
    member: Member,
    category: str,
    target_week: date,
    last_role: Dict[int, Dict[str, date]],
    last_sister_fm: Dict[int, date],
    rules: RulesConfig,
) -> Tuple[bool, str]:
    uid = member.hourglass_user_id
    lr = last_role.get(uid, {})
    if category in lr:
        gap = weeks_between(lr[category], target_week)
        if gap < rules.spacing.same_role_min_weeks:
            return False, f"espaçamento {category}: {gap} semanas < {rules.spacing.same_role_min_weeks}"
    if category in SISTER_FM_CATEGORIES or (
        category in rules.sisters_only_categories and category.startswith("apply")
    ):
        if uid in last_sister_fm:
            gap = weeks_between(last_sister_fm[uid], target_week)
            if gap < rules.spacing.sister_fm_min_weeks:
                return False, f"espaçamento irmã FM: {gap} semanas < {rules.spacing.sister_fm_min_weeks}"
    return True, ""


def pick_candidate(
    category: str,
    members: List[Member],
    counts: Dict[str, Dict[str, int]],
    target_week: date,
    last_role: Dict[int, Dict[str, date]],
    last_sister_fm: Dict[int, date],
    rules: RulesConfig,
    excluded_member_ids: Set[str],
) -> Optional[Tuple[Member, Dict[str, Any]]]:
    cat_counts = counts.get(category, {})
    ranked: List[Tuple[int, str, Member]] = []
    for m in members:
        if m.id in excluded_member_ids:
            continue
        ok, reason = spacing_ok(m, category, target_week, last_role, last_sister_fm, rules)
        if not ok:
            continue
        c = cat_counts.get(m.id, 0)
        ranked.append((c, m.display_name.lower(), m))
    if not ranked:
        return None
    ranked.sort(key=lambda x: (x[0], x[1]))
    winner = ranked[0][2]
    rationale = {
        "category": category,
        "prior_count": ranked[0][0],
        "candidates_considered": len(ranked),
        "rule_sisters_only": category in rules.sisters_only_categories,
    }
    return winner, rationale


def suggest_week(
    *,
    target_week: date,
    members: List[Member],
    history: List[Dict[str, Any]],
    rules: RulesConfig,
    eligible_by_category: Dict[str, Set[str]],
    categories: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    members = filter_members_for_rules(members, rules)
    members_by_uid = {m.hourglass_user_id: m for m in members}
    eligible_by_category = remap_eligible_by_category(eligible_by_category, rules)
    counts, last_role, last_sister_fm = build_history_index(
        history,
        rules=rules,
        members_by_uid=members_by_uid,
    )
    cats = categories or SUGGESTION_ORDER
    suggestions: List[Dict[str, Any]] = []
    used_this_week: Set[str] = set()
    assigned_students: Dict[str, str] = {}

    for category in cats:
        elig_ids = eligible_by_category.get(category)
        pool = eligible_for_category(members, category, elig_ids, rules)
        excluded = set(used_this_week)
        # Evitar mesma pessoa como estudante e assistente no mesmo slot FM
        prefix = category.replace("_assistant", "")
        if category.endswith("_assistant") and prefix in assigned_students:
            excluded.add(assigned_students[prefix])

        picked = pick_candidate(
            category,
            pool,
            counts,
            target_week,
            last_role,
            last_sister_fm,
            rules,
            excluded,
        )
        if not picked:
            suggestions.append(
                {
                    "week_date": target_week.isoformat(),
                    "role_category": category,
                    "member_id": None,
                    "hourglass_user_id": None,
                    "display_name": None,
                    "status": "draft",
                    "rationale": {"error": "nenhum candidato elegível"},
                }
            )
            continue
        member, rationale = picked
        used_this_week.add(member.id)
        if category.startswith("apply") and not category.endswith("_assistant"):
            assigned_students[category] = member.id

        # Simular incremento para próximas categorias na mesma rodada
        counts.setdefault(category, {})
        counts[category][member.id] = counts[category].get(member.id, 0) + 1
        uid = member.hourglass_user_id
        last_role.setdefault(uid, {})[category] = target_week
        if category in SISTER_FM_CATEGORIES:
            last_sister_fm[uid] = target_week

        suggestions.append(
            {
                "week_date": target_week.isoformat(),
                "role_category": category,
                "member_id": member.id,
                "hourglass_user_id": member.hourglass_user_id,
                "display_name": member.display_name,
                "status": "draft",
                "rationale": rationale,
            }
        )
    return suggestions
