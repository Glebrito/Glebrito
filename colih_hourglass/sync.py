from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .config import Settings
from .hourglass_api import (
    fetch_meeting,
    fetch_privileges,
    fetch_schedule,
    fetch_users_directory,
    load_json_file,
    load_session,
    resolve_session_path,
)
from .rules_engine import SISTER_FM_CATEGORIES
from .schedule_parse import (
    extract_schedule_roots,
    iter_assignments_from_week,
    parse_all_assignments,
    parse_privileges,
    parse_users,
)
from .supabase_client import SupabaseClient

FEMALE_INFER_CATEGORIES = frozenset(SISTER_FM_CATEGORIES)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _looks_like_placeholder(name: Optional[str]) -> bool:
    if not name or not str(name).strip():
        return True
    s = str(name).strip()
    return bool(re.match(r"^id:\d+$", s, re.I))


def _pick_better_name(current: Optional[str], new: Optional[str]) -> str:
    cur = (current or "").strip()
    neu = (new or "").strip()
    if _looks_like_placeholder(cur) and not _looks_like_placeholder(neu):
        return neu
    if not cur and neu:
        return neu
    if len(neu) > len(cur) and not _looks_like_placeholder(neu):
        return neu
    return cur or neu or ""


def _normalize_sex_db(value: Any) -> Optional[str]:
    if not value:
        return None
    v = str(value).strip().lower()
    if v in ("female", "f", "feminino"):
        return "Female"
    if v in ("male", "m", "masculino"):
        return "Male"
    return "Unknown"


def _pick_better_sex(current: Optional[str], new: Optional[str]) -> Optional[str]:
    if new in ("Female", "Male"):
        if current in ("Female", "Male"):
            return current
        return new
    return current or new


def _uid_from_privilege_item(raw: Any) -> Optional[int]:
    if isinstance(raw, bool):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _ids_from_hourglass_privilege_dict(payload: Dict[str, Any]) -> Tuple[Dict[int, List[str]], Set[int]]:
    """Dict categoria → [user_id, ...] (export privileges do Hourglass)."""
    privs_by_id: Dict[int, List[str]] = {}
    all_ids: Set[int] = set()
    for cat, vals in payload.items():
        if not isinstance(vals, list):
            continue
        for raw in vals:
            uid = _uid_from_privilege_item(raw)
            if uid is None:
                continue
            all_ids.add(uid)
            privs_by_id.setdefault(uid, []).append(str(cat))
    return privs_by_id, all_ids


def _is_hourglass_privilege_map(payload: Any) -> bool:
    if not isinstance(payload, dict) or not payload:
        return False
    if any(k in payload for k in ("users", "publishers", "data")):
        return False
    inner = payload.get("privileges")
    if isinstance(inner, dict) and inner:
        return all(isinstance(v, list) for v in inner.values() if v is not None)
    lists = [v for v in payload.values() if isinstance(v, list)]
    if not lists:
        return False
    return not any(isinstance(item, dict) for lst in lists for item in lst[:3])


def infer_sex_from_assignments(
    rows: List[Tuple[str, str, Optional[int], Optional[str]]],
) -> Dict[int, str]:
    """Conservador: apply1–3 (+ assistentes) → Female se sexo ainda desconhecido."""
    female_ids: Set[int] = set()
    for _week, category, uid, _label in rows:
        if uid is None:
            continue
        if category in FEMALE_INFER_CATEGORIES:
            female_ids.add(int(uid))
    return {uid: "Female" for uid in female_ids}


def members_from_privileges(
    congregation_id: str,
    priv_payload: Any,
    *,
    user_names: Optional[Dict[str, str]] = None,
    sex_by_id: Optional[Dict[int, str]] = None,
) -> List[Dict[str, Any]]:
    sex_by_id = sex_by_id or {}
    user_names = user_names or {}
    try:
        names, _eligible = parse_privileges(priv_payload)
    except Exception:
        names = {}
    for uid, label in user_names.items():
        names[uid] = _pick_better_name(names.get(uid), label)

    rows: List[Dict[str, Any]] = []
    users: List[Dict[str, Any]] = []
    privs_by_id: Dict[int, List[str]] = {}
    extra_ids: Set[int] = set()

    if isinstance(priv_payload, dict):
        for key in ("users", "publishers", "data"):
            val = priv_payload.get(key)
            if isinstance(val, list) and val and isinstance(val[0], dict):
                users = val
                break
        if not users and _is_hourglass_privilege_map(priv_payload):
            map_src = priv_payload.get("privileges") if isinstance(priv_payload.get("privileges"), dict) else priv_payload
            if isinstance(map_src, dict):
                privs_by_id, extra_ids = _ids_from_hourglass_privilege_dict(map_src)
    elif isinstance(priv_payload, list):
        if priv_payload and isinstance(priv_payload[0], dict):
            users = priv_payload

    seen = set()
    for u in users:
        if not isinstance(u, dict):
            continue
        uid = u.get("id") or u.get("user_id")
        if uid is None:
            continue
        hid = int(uid)
        if hid in seen:
            continue
        seen.add(hid)
        fn = u.get("first_name") or ""
        ln = u.get("last_name") or ""
        name = _pick_better_name(names.get(str(hid)), f"{fn} {ln}".strip() or None)
        if not name:
            name = f"id:{hid}"
        privs = u.get("privileges") or u.get("scheduling_privileges") or []
        if isinstance(privs, dict):
            privs = [k for k, v in privs.items() if v]
        sex = sex_by_id.get(hid) or u.get("sex") or u.get("gender")
        rows.append(
            {
                "congregation_id": congregation_id,
                "hourglass_user_id": hid,
                "display_name": name,
                "sex": _normalize_sex_db(sex),
                "privileges": privs if isinstance(privs, list) else [],
                "metadata": {},
                "updated_at": _utc_now(),
            }
        )

    for hid in extra_ids:
        if hid in seen:
            continue
        seen.add(hid)
        name = _pick_better_name(names.get(str(hid)), user_names.get(str(hid))) or f"id:{hid}"
        privs = privs_by_id.get(hid, [])
        sex = sex_by_id.get(hid)
        rows.append(
            {
                "congregation_id": congregation_id,
                "hourglass_user_id": hid,
                "display_name": name,
                "sex": _normalize_sex_db(sex),
                "privileges": privs,
                "metadata": {},
                "updated_at": _utc_now(),
            }
        )

    return rows


def upsert_members_and_map(
    sb: SupabaseClient,
    congregation_id: str,
    member_rows: List[Dict[str, Any]],
    id_names: Dict[str, str],
) -> Dict[int, str]:
    """Garante members para todos os ids vistos; retorna hourglass_user_id → member uuid."""
    existing = sb.select(
        "members",
        filters=f"congregation_id=eq.{congregation_id}",
        columns="id,hourglass_user_id,display_name,sex,privileges",
    )
    by_hid: Dict[int, Dict[str, Any]] = {int(m["hourglass_user_id"]): m for m in existing}

    merged: Dict[int, Dict[str, Any]] = {}
    for row in member_rows:
        hid = int(row["hourglass_user_id"])
        prev = merged.get(hid) or by_hid.get(hid) or {}
        merged[hid] = {
            "congregation_id": congregation_id,
            "hourglass_user_id": hid,
            "display_name": _pick_better_name(prev.get("display_name"), row.get("display_name")),
            "sex": _pick_better_sex(prev.get("sex"), row.get("sex")),
            "privileges": row.get("privileges") if row.get("privileges") else prev.get("privileges") or [],
            "metadata": row.get("metadata") if row.get("metadata") else prev.get("metadata") or {},
            "updated_at": _utc_now(),
        }

    for hid_str, label in id_names.items():
        try:
            hid = int(hid_str)
        except ValueError:
            continue
        if hid in merged:
            merged[hid]["display_name"] = _pick_better_name(merged[hid]["display_name"], label)
            continue
        prev = by_hid.get(hid, {})
        merged[hid] = {
            "congregation_id": congregation_id,
            "hourglass_user_id": hid,
            "display_name": _pick_better_name(prev.get("display_name"), label),
            "sex": prev.get("sex"),
            "privileges": prev.get("privileges") or [],
            "metadata": prev.get("metadata") or {},
            "updated_at": _utc_now(),
        }

    out_rows = list(merged.values())
    if out_rows:
        sb.upsert("members", out_rows, on_conflict="congregation_id,hourglass_user_id")
    db_members = sb.select(
        "members",
        filters=f"congregation_id=eq.{congregation_id}",
        columns="id,hourglass_user_id,display_name,sex,privileges",
    )
    return {int(m["hourglass_user_id"]): str(m["id"]) for m in db_members}


def _merge_id_names_from_rows(
    id_names: Dict[str, str],
    rows: List[Tuple[str, str, Optional[int], Optional[str]]],
) -> None:
    for _week, _cat, uid, label in rows:
        if uid is None or not label:
            continue
        key = str(uid)
        id_names[key] = _pick_better_name(id_names.get(key), label)


def sync_from_payloads(
    settings: Settings,
    *,
    schedule_payload: Any,
    privileges_payload: Optional[Any] = None,
    meeting_payload: Optional[Any] = None,
    users_payload: Optional[Any] = None,
    source: str = "import",
) -> Dict[str, Any]:
    sb = SupabaseClient(settings)
    congregation_id = sb.congregation_id_for_lgroup(settings.lgroup)
    run = sb.insert(
        "sync_runs",
        {
            "congregation_id": congregation_id,
            "status": "running",
            "source": source,
            "stats": {},
        },
    )
    run_id = run[0]["id"]
    stats: Dict[str, Any] = {"assignments_upserted": 0, "weeks": 0, "members": 0}

    try:
        all_rows, id_names = parse_all_assignments(schedule_payload)
        if users_payload is not None:
            for uid, label in parse_users(users_payload).items():
                id_names[uid] = _pick_better_name(id_names.get(uid), label)
        _merge_id_names_from_rows(id_names, all_rows)

        sex_by_id = infer_sex_from_assignments(all_rows)
        user_name_map = parse_users(users_payload) if users_payload is not None else {}

        member_rows: List[Dict[str, Any]] = []
        if privileges_payload is not None or users_payload is not None:
            member_rows = members_from_privileges(
                congregation_id,
                privileges_payload if privileges_payload is not None else users_payload,
                user_names=user_name_map,
                sex_by_id=sex_by_id,
            )
        uid_to_member = upsert_members_and_map(sb, congregation_id, member_rows, id_names)
        stats["members"] = len(uid_to_member)

        assignment_rows: List[Dict[str, Any]] = []
        weeks = extract_schedule_roots(schedule_payload)
        stats["weeks"] = len([w for w in weeks if isinstance(w, dict)])

        for week in weeks:
            if not isinstance(week, dict):
                continue
            week_date = str(week.get("date", ""))[:10]
            if week_date:
                sb.upsert(
                    "meeting_programs",
                    [
                        {
                            "congregation_id": congregation_id,
                            "week_date": week_date,
                            "schedule_json": week,
                            "meeting_json": None,
                            "synced_at": _utc_now(),
                        }
                    ],
                    on_conflict="congregation_id,week_date",
                )
            for wd, cat, uid, label in iter_assignments_from_week(week, id_names):
                if not uid:
                    continue
                mid = uid_to_member.get(uid)
                assignment_rows.append(
                    {
                        "congregation_id": congregation_id,
                        "member_id": mid,
                        "hourglass_user_id": uid,
                        "week_date": wd,
                        "role_category": cat,
                        "assignee_name": label,
                        "source": source,
                    }
                )

        chunk = 200
        for i in range(0, len(assignment_rows), chunk):
            sb.upsert(
                "assignment_history",
                assignment_rows[i : i + chunk],
                on_conflict="congregation_id,week_date,role_category,hourglass_user_id",
            )
        stats["assignments_upserted"] = len(assignment_rows)

        sb.patch(
            "sync_runs",
            f"id=eq.{run_id}",
            {"status": "success", "finished_at": _utc_now(), "stats": stats},
        )
        return {"run_id": run_id, "status": "success", "stats": stats}
    except Exception as exc:
        sb.patch(
            "sync_runs",
            f"id=eq.{run_id}",
            {
                "status": "failed",
                "finished_at": _utc_now(),
                "error_message": str(exc),
                "stats": stats,
            },
        )
        raise


def sync_from_hourglass(
    settings: Settings,
    date_from: str,
    date_to: str,
    session_path: Optional[Path] = None,
) -> Dict[str, Any]:
    path = resolve_session_path(session_path)
    if not path:
        raise RuntimeError(
            "Sem sessão Hourglass nesta VM. Use sync --from-file ou no PC: "
            "python hourglass_cli.py fetch all --out export.json && colih_hourglass import-rotation export.json"
        )
    session = load_session(path)
    schedule = fetch_schedule(session, date_from, date_to, settings.lgroup)
    priv = fetch_privileges(session, settings.lgroup)
    users = fetch_users_directory(session, settings.lgroup)
    try:
        meeting = fetch_meeting(session, date_from, date_to, settings.lgroup)
    except RuntimeError:
        meeting = None
    return sync_from_payloads(
        settings,
        schedule_payload=schedule,
        privileges_payload=priv,
        meeting_payload=meeting,
        users_payload=users,
        source="hourglass_api",
    )


def import_rotation_file(settings: Settings, path: Path) -> Dict[str, Any]:
    payload = load_json_file(path)
    priv = None
    users = None
    if isinstance(payload, dict):
        priv = payload.get("privileges")
        users = payload.get("users")
        sched = payload.get("schedules") or payload.get("schedule") or payload
    else:
        sched = payload
    return sync_from_payloads(
        settings,
        schedule_payload=sched,
        privileges_payload=priv,
        users_payload=users,
        source=f"file:{path.name}",
    )
