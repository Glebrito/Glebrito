from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import Settings
from .hourglass_api import (
    fetch_meeting,
    fetch_privileges,
    fetch_schedule,
    load_json_file,
    load_session,
    resolve_session_path,
)
from .schedule_parse import iter_assignments_from_week, parse_all_assignments, parse_privileges, extract_schedule_roots
from .supabase_client import SupabaseClient


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def members_from_privileges(
    congregation_id: str,
    priv_payload: Any,
    sex_by_id: Optional[Dict[int, str]] = None,
) -> List[Dict[str, Any]]:
    sex_by_id = sex_by_id or {}
    try:
        names, _eligible = parse_privileges(priv_payload)
    except Exception:
        names = {}
    rows: List[Dict[str, Any]] = []
    # Re-walk privilege JSON for privilege lists
    users: List[Dict[str, Any]] = []
    if isinstance(priv_payload, dict):
        for key in ("users", "publishers", "data"):
            val = priv_payload.get(key)
            if isinstance(val, list):
                users = val
                break
    elif isinstance(priv_payload, list):
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
        name = names.get(str(hid)) or f"{fn} {ln}".strip() or f"id:{hid}"
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
    return rows


def _normalize_sex_db(value: Any) -> Optional[str]:
    if not value:
        return None
    v = str(value).strip().lower()
    if v in ("female", "f", "feminino"):
        return "Female"
    if v in ("male", "m", "masculino"):
        return "Male"
    return "Unknown"


def upsert_members_and_map(
    sb: SupabaseClient,
    congregation_id: str,
    member_rows: List[Dict[str, Any]],
    id_names: Dict[str, str],
) -> Dict[int, str]:
    """Garante members para todos os ids vistos; retorna hourglass_user_id → member uuid."""
    for hid_str, label in id_names.items():
        try:
            hid = int(hid_str)
        except ValueError:
            continue
        if any(r["hourglass_user_id"] == hid for r in member_rows):
            continue
        member_rows.append(
            {
                "congregation_id": congregation_id,
                "hourglass_user_id": hid,
                "display_name": label,
                "sex": None,
                "privileges": [],
                "metadata": {},
                "updated_at": _utc_now(),
            }
        )
    if member_rows:
        sb.upsert("members", member_rows, on_conflict="congregation_id,hourglass_user_id")
    db_members = sb.select(
        "members",
        filters=f"congregation_id=eq.{congregation_id}",
        columns="id,hourglass_user_id,display_name,sex,privileges",
    )
    return {int(m["hourglass_user_id"]): str(m["id"]) for m in db_members}


def sync_from_payloads(
    settings: Settings,
    *,
    schedule_payload: Any,
    privileges_payload: Optional[Any] = None,
    meeting_payload: Optional[Any] = None,
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
        member_rows = []
        if privileges_payload:
            member_rows = members_from_privileges(congregation_id, privileges_payload)
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

        # Batch upsert assignments
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
    try:
        meeting = fetch_meeting(session, date_from, date_to, settings.lgroup)
    except RuntimeError:
        meeting = None
    return sync_from_payloads(
        settings,
        schedule_payload=schedule,
        privileges_payload=priv,
        meeting_payload=meeting,
        source="hourglass_api",
    )


def import_rotation_file(settings: Settings, path: Path) -> Dict[str, Any]:
    payload = load_json_file(path)
    priv = None
    if isinstance(payload, dict) and "privileges" in payload:
        priv = payload.get("privileges")
        sched = payload.get("schedules") or payload.get("schedule") or payload
    else:
        sched = payload
    return sync_from_payloads(settings, schedule_payload=sched, privileges_payload=priv, source=f"file:{path.name}")
