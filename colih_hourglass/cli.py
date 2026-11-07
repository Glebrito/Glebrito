from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Set

from .config import Settings
from .rules_engine import (
    Member,
    RulesConfig,
    SUGGESTION_ORDER,
    load_rules_from_db,
    suggest_week,
)
from .schedule_parse import parse_privileges, parse_week_date
from .sync import import_rotation_file, sync_from_hourglass
from .supabase_client import SupabaseClient


def _load_members(sb: SupabaseClient, congregation_id: str) -> List[Member]:
    rows = sb.select(
        "members",
        filters=f"congregation_id=eq.{congregation_id}&active=eq.true",
        columns="id,hourglass_user_id,display_name,sex,privileges",
    )
    out: List[Member] = []
    for r in rows:
        privs = r.get("privileges") or []
        if isinstance(privs, str):
            try:
                privs = json.loads(privs)
            except json.JSONDecodeError:
                privs = []
        priv_set: Set[str] = set()
        for p in privs:
            if isinstance(p, str):
                priv_set.add(p)
        out.append(
            Member(
                id=str(r["id"]),
                hourglass_user_id=int(r["hourglass_user_id"]),
                display_name=r.get("display_name") or f"id:{r['hourglass_user_id']}",
                sex=r.get("sex"),
                privileges=priv_set,
            )
        )
    return out


def _eligible_map_from_privileges(priv_payload: Any) -> Dict[str, Set[str]]:
    if not priv_payload:
        return {}
    try:
        _names, eligible = parse_privileges(priv_payload)
    except Exception:
        return {}
    # Converter categorias → ids hourglass
    out: Dict[str, Set[str]] = {}
    for cat, ids in eligible.items():
        out[cat] = set(str(x) for x in ids)
    return out


def cmd_sync(args: argparse.Namespace) -> None:
    settings = Settings.from_env()
    if args.from_file:
        result = import_rotation_file(settings, Path(args.from_file))
    else:
        result = sync_from_hourglass(settings, args.date_from, args.date_to)
    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_import_rotation(args: argparse.Namespace) -> None:
    settings = Settings.from_env()
    result = import_rotation_file(settings, Path(args.file))
    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_suggest_next(args: argparse.Namespace) -> None:
    settings = Settings.from_env()
    sb = SupabaseClient(settings)
    congregation_id = sb.congregation_id_for_lgroup(settings.lgroup)
    week = args.week
    if not week:
        week = (datetime.utcnow().date() + timedelta(days=(7 - datetime.utcnow().weekday()))).isoformat()

    rules_rows = sb.select("rules_config", filters=f"congregation_id=eq.{congregation_id}")
    spacing_rows = sb.select(
        "spacing_constraints",
        filters=f"congregation_id=eq.{congregation_id}&active=eq.true",
    )
    rules = load_rules_from_db(rules_rows, spacing_rows)

    members = _load_members(sb, congregation_id)
    history = sb.select(
        "assignment_history",
        filters=f"congregation_id=eq.{congregation_id}",
        order="week_date.desc",
        limit=5000,
    )
    eligible: Dict[str, Set[str]] = {}
    suggestions = suggest_week(
        target_week=parse_week_date(week),
        members=members,
        history=history,
        rules=rules,
        eligible_by_category=eligible,
        categories=args.categories.split(",") if args.categories else None,
    )

    run_id = None
    if args.persist:
        for s in suggestions:
            s["congregation_id"] = congregation_id
            s["suggestion_run_id"] = run_id
        sb.upsert(
            "draft_assignments",
            [
                {
                    "congregation_id": congregation_id,
                    "week_date": s["week_date"],
                    "role_category": s["role_category"],
                    "member_id": s.get("member_id"),
                    "hourglass_user_id": s.get("hourglass_user_id"),
                    "display_name": s.get("display_name"),
                    "status": s.get("status", "draft"),
                    "rationale": s.get("rationale", {}),
                }
                for s in suggestions
            ],
            on_conflict="congregation_id,week_date,role_category",
        )

    out_path = Path(args.out) if args.out else None
    doc = {"week": week, "lgroup": settings.lgroup, "suggestions": suggestions}
    text = json.dumps(doc, indent=2, ensure_ascii=False)
    if out_path:
        out_path.write_text(text + "\n", encoding="utf-8")
        print(f"Sugestões gravadas em {out_path}")
    else:
        print(text)


def cmd_export_draft(args: argparse.Namespace) -> None:
    settings = Settings.from_env()
    sb = SupabaseClient(settings)
    congregation_id = sb.congregation_id_for_lgroup(settings.lgroup)
    filters = f"congregation_id=eq.{congregation_id}&week_date=eq.{args.week}"
    if args.status:
        filters += f"&status=eq.{args.status}"
    drafts = sb.select("draft_assignments", filters=filters, order="role_category.asc")
    export = {
        "meta": {
            "week": args.week,
            "lgroup": settings.lgroup,
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "hourglass_apply": "stub — use week_after + schedule put-core --body-file no PC",
        },
        "assignments": drafts,
        "patch_by_role": {
            d["role_category"]: d.get("hourglass_user_id")
            for d in drafts
            if d.get("hourglass_user_id")
        },
    }
    out = Path(args.out) if args.out else Path(f"draft-{args.week}.json")
    out.write_text(json.dumps(export, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Rascunho exportado: {out}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="colih-hourglass", description="Hourglass ↔ Supabase (Colih)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("sync", help="Baixar Hourglass e gravar no Supabase")
    s.add_argument("--from", dest="date_from", default="2025-04-01")
    s.add_argument("--to", dest="date_to", default="2026-12-31")
    s.add_argument(
        "--from-file",
        help="JSON local (export fetch all) em vez da API",
    )
    s.set_defaults(func=cmd_sync)

    ir = sub.add_parser("import-rotation", help="Importar schedule/privileges de arquivo JSON")
    ir.add_argument("file")
    ir.set_defaults(func=cmd_import_rotation)

    sn = sub.add_parser("suggest-next", help="Gerar sugestões para uma semana")
    sn.add_argument("--week", help="YYYY-MM-DD (segunda da semana de serviço)")
    sn.add_argument("--categories", help="Lista separada por vírgula (opcional)")
    sn.add_argument("--persist", action="store_true", help="Gravar em draft_assignments")
    sn.add_argument("--out", help="Arquivo JSON de saída")
    sn.set_defaults(func=cmd_suggest_next)

    ex = sub.add_parser("export-draft", help="Exportar rascunho para revisão / Hourglass")
    ex.add_argument("--week", required=True)
    ex.add_argument("--status", default="draft")
    ex.add_argument("--out")
    ex.set_defaults(func=cmd_export_draft)

    return p


def main(argv: List[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
