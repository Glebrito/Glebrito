from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .config import Settings
from .rules_engine import (
    Member,
    RulesConfig,
    SUGGESTION_ORDER,
    load_rules_from_db,
    suggest_week,
)
from .schedule_parse import parse_privileges, parse_week_date
from .hourglass_api import load_session, resolve_session_path, session_setup_help_pt
from .sync import import_rotation_file, sync_from_hourglass
from .supabase_client import SupabaseClient
from .web_panel import ROLE_LABELS_PT


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


def _history_name_hints(history: List[Dict[str, Any]]) -> Dict[int, str]:
    out: Dict[int, str] = {}
    for h in history:
        uid = h.get("hourglass_user_id")
        name = h.get("assignee_name")
        if uid is None or not name:
            continue
        if str(name).startswith("id:"):
            continue
        out[int(uid)] = str(name).strip()
    return out


def _enrich_member_display_names(members: List[Member], hints: Dict[int, str]) -> None:
    for m in members:
        if _looks_like_placeholder(m.display_name) and m.hourglass_user_id in hints:
            m.display_name = hints[m.hourglass_user_id]


def _looks_like_placeholder(name: Optional[str]) -> bool:
    if not name:
        return True
    import re

    return bool(re.match(r"^id:\d+$", str(name).strip(), re.I))


def _enrich_suggestions(
    suggestions: List[Dict[str, Any]],
    hints: Dict[int, str],
    members_by_uid: Dict[int, Member],
) -> None:
    for s in suggestions:
        uid = s.get("hourglass_user_id")
        dn = s.get("display_name")
        if dn and not _looks_like_placeholder(dn):
            continue
        if uid is not None:
            hint = hints.get(int(uid))
            if hint:
                s["display_name"] = hint
                continue
            mem = members_by_uid.get(int(uid))
            if mem and not _looks_like_placeholder(mem.display_name):
                s["display_name"] = mem.display_name


def _next_monday_iso() -> str:
    today = datetime.utcnow().date()
    if today.weekday() == 0:
        return today.isoformat()
    return (today + timedelta(days=(7 - today.weekday()))).isoformat()


def print_suggestions_markdown(doc: Dict[str, Any]) -> None:
    week = doc.get("week", "")
    print(f"\n## Sugestões — semana {week}\n")
    print("| Parte | Nome | Status |")
    print("| --- | --- | --- |")
    for s in doc.get("suggestions") or []:
        role_key = s.get("role_category", "")
        label = ROLE_LABELS_PT.get(role_key, role_key)
        name = s.get("display_name") or "—"
        if _looks_like_placeholder(str(name)):
            name = "—"
        status = s.get("status") or ""
        print(f"| {label} | {name} | {status} |")
    print()


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


def cmd_sync_now(args: argparse.Namespace) -> None:
    """Alias legado → mesmo fluxo que atualizar (sem sugestão)."""
    args.suggest = False
    args.week = None
    args.persist = False
    args.json_out = None
    args.env_file = getattr(args, "env_file", None)
    cmd_atualizar(args)


def cmd_atualizar(args: argparse.Namespace) -> None:
    if getattr(args, "env_file", None):
        from .env_loader import load_env_file

        load_env_file(Path(args.env_file))

    settings = Settings.from_env()
    path = resolve_session_path(None)
    if not path:
        print(session_setup_help_pt(), file=sys.stderr)
        sys.exit(2)

    try:
        load_session(path)
        result = sync_from_hourglass(
            settings,
            args.date_from,
            args.date_to,
            session_path=path,
        )
    except RuntimeError as exc:
        msg = str(exc)
        if "401" in msg or "sessão" in msg.lower():
            print(session_setup_help_pt(), file=sys.stderr)
            sys.exit(2)
        print(msg, file=sys.stderr)
        sys.exit(1)

    week: Optional[str] = args.week
    if getattr(args, "suggest", False) and not week:
        week = _next_monday_iso()

    output: Dict[str, Any] = {"sync": result}
    if week:
        doc = run_suggest_week(settings, week=week, persist=getattr(args, "persist", False))
        output["suggestions"] = doc
        print(f"Sync OK: {result.get('status')} — {result.get('stats')}")
        print_suggestions_markdown(doc)
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))

    if getattr(args, "json_out", None):
        Path(args.json_out).write_text(
            json.dumps(output, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"JSON gravado em {args.json_out}")


def cmd_import_rotation(args: argparse.Namespace) -> None:
    settings = Settings.from_env()
    result = import_rotation_file(settings, Path(args.file))
    print(json.dumps(result, indent=2, ensure_ascii=False))


def run_suggest_week(
    settings: Settings,
    *,
    week: str | None = None,
    persist: bool = False,
    categories: List[str] | None = None,
) -> Dict[str, Any]:
    sb = SupabaseClient(settings)
    congregation_id = sb.congregation_id_for_lgroup(settings.lgroup)
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
    name_hints = _history_name_hints(history)
    _enrich_member_display_names(members, name_hints)
    members_by_uid = {m.hourglass_user_id: m for m in members}
    eligible: Dict[str, Set[str]] = {}
    suggestions = suggest_week(
        target_week=parse_week_date(week),
        members=members,
        history=history,
        rules=rules,
        eligible_by_category=eligible,
        categories=categories,
    )
    _enrich_suggestions(suggestions, name_hints, members_by_uid)

    run_id = None
    if persist:
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

    return {"week": week, "lgroup": settings.lgroup, "suggestions": suggestions}


def cmd_suggest_next(args: argparse.Namespace) -> None:
    settings = Settings.from_env()
    doc = run_suggest_week(
        settings,
        week=args.week,
        persist=args.persist,
        categories=args.categories.split(",") if args.categories else None,
    )
    out_path = Path(args.out) if args.out else None
    text = json.dumps(doc, indent=2, ensure_ascii=False)
    if out_path:
        out_path.write_text(text + "\n", encoding="utf-8")
        print(f"Sugestões gravadas em {out_path}")
    else:
        print(text)


def build_draft_export(settings: Settings, week: str, status: str = "draft") -> Dict[str, Any]:
    sb = SupabaseClient(settings)
    congregation_id = sb.congregation_id_for_lgroup(settings.lgroup)
    filters = f"congregation_id=eq.{congregation_id}&week_date=eq.{week}"
    if status:
        filters += f"&status=eq.{status}"
    drafts = sb.select("draft_assignments", filters=filters, order="role_category.asc")
    return {
        "meta": {
            "week": week,
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


def cmd_export_draft(args: argparse.Namespace) -> None:
    settings = Settings.from_env()
    export = build_draft_export(settings, args.week, args.status or "draft")
    out = Path(args.out) if args.out else Path(f"draft-{args.week}.json")
    out.write_text(json.dumps(export, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Rascunho exportado: {out}")


def cmd_serve(args: argparse.Namespace) -> None:
    if args.env_file:
        from .env_loader import load_env_file

        n = load_env_file(Path(args.env_file))
        print(f"Variáveis carregadas de {args.env_file}: {n} novas chave(s).")
    from .web_panel import run_server

    run_server(host="127.0.0.1", port=args.port)


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

    snw = sub.add_parser(
        "sync-now",
        help="Sync API se HG_SESSION válida; senão instruções para snippet + painel",
    )
    snw.add_argument("--from", dest="date_from", default="2025-04-01")
    snw.add_argument("--to", dest="date_to", default="2026-12-31")
    snw.set_defaults(func=cmd_sync_now)

    def _add_atualizar_parser(name: str) -> None:
        ap = sub.add_parser(
            name,
            help="Baixar Hourglass (sessão) → Supabase; opcional --week com tabela markdown",
        )
        ap.add_argument("--from", dest="date_from", default="2025-04-01")
        ap.add_argument("--to", dest="date_to", default="2026-12-31")
        ap.add_argument("--week", help="Após sync, gerar sugestões desta segunda (AAAA-MM-DD)")
        ap.add_argument(
            "--suggest",
            action="store_true",
            help="Após sync, sugerir próxima segunda (usado pelo rodizio.bat)",
        )
        ap.add_argument("--persist", action="store_true", help="Gravar rascunho no Supabase")
        ap.add_argument("--json-out", help="Gravar sync (+ sugestões) em JSON")
        ap.add_argument(
            "--env-file",
            help="hourglass.env antes de rodar (SUPABASE_*, HOURGLASS_LGROUP)",
        )
        ap.set_defaults(func=cmd_atualizar)

    _add_atualizar_parser("atualizar")
    _add_atualizar_parser("pull-and-sync")

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

    sv = sub.add_parser("serve", help="Painel web local (127.0.0.1)")
    sv.add_argument("--port", type=int, default=8765, help="Porta TCP (padrão 8765)")
    sv.add_argument(
        "--env-file",
        help="Arquivo .env ou hourglass.env (KEY=valor) antes de iniciar o servidor",
    )
    sv.set_defaults(func=cmd_serve)

    return p


def main(argv: List[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
