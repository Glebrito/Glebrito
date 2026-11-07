#!/usr/bin/env python3
"""
Relatório de rodízio justo para designações Hourglass (midweek / scheduling/mm).

Uso:
  python3 hourglass_rotation_report.py --schedule path.json [--privileges path.json] [--out report.md]

Somente biblioteca padrão. Ver docs/rodizio-designacoes.md.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, DefaultDict, Dict, Iterable, List, Optional, Set, Tuple

# Chaves de metadado / estrutura — não são categorias de designação
SKIP_KEYS = frozenset(
    {
        "meta",
        "meetings",
        "meeting",
        "events",
        "settings",
        "subs",
        "substitutions",
        "week",
        "week_start",
        "week_end",
        "lgroup",
        "language_group",
        "title",
        "theme",
        "notes",
        "note",
        "status",
        "published",
        "draft",
        "version",
        "source",
        "fetched_at",
        "from",
        "to",
        "parts_meta",
        "materials",
        "duration",
        "start",
        "end",
        "time",
        "song",
        "songs",
    }
)

# Normalização de nomes de campo → categoria (slug interno, título PT)
ROLE_ALIASES: Dict[str, str] = {
    "chairman": "chairman",
    "presidente": "chairman",
    "auxiliary": "auxiliary_counselor",
    "auxiliary_counselor": "auxiliary_counselor",
    "auxiliarycounselor": "auxiliary_counselor",
    "conselheiro_auxiliar": "auxiliary_counselor",
    "opening_prayer": "opening_prayer",
    "openingprayer": "opening_prayer",
    "openprayer": "opening_prayer",
    "open_prayer": "opening_prayer",
    "prayer_opening": "opening_prayer",
    "closing_prayer": "closing_prayer",
    "closingprayer": "closing_prayer",
    "closeprayer": "closing_prayer",
    "close_prayer": "closing_prayer",
    "prayer_closing": "closing_prayer",
    "treasures": "treasures_talk",
    "treasures_talk": "treasures_talk",
    "treasurestalk": "treasures_talk",
    "treasures_talk_part": "treasures_talk",
    "tt": "treasures_talk",
    "gems": "spiritual_gems",
    "spiritual_gems": "spiritual_gems",
    "spiritualgems": "spiritual_gems",
    "bible_reading": "bible_reading",
    "biblereading": "bible_reading",
    "bible_reader": "bible_reading",
    "reader": "bible_reading",
    "school_overseer": "school_overseer",
    "apply1": "apply1",
    "apply2": "apply2",
    "apply3": "apply3",
    "apply4": "apply4",
    "apply1_assistant": "apply1_assistant",
    "apply2_assistant": "apply2_assistant",
    "apply3_assistant": "apply3_assistant",
    "apply4_assistant": "apply4_assistant",
    "apply1assistant": "apply1_assistant",
    "apply2assistant": "apply2_assistant",
    "apply3assistant": "apply3_assistant",
    "apply4assistant": "apply4_assistant",
    "living1": "living1",
    "living2": "living2",
    "living3": "living3",
    "cbs": "cbs",
    "cbs_conductor": "cbs",
    "cbs_reader": "cbs_reader",
    "cbsreader": "cbs_reader",
    "host": "host",
    "cohost": "cohost",
    "co_host": "cohost",
    "zoom_attendant": "zoom_attendant",
    "zoomattendant": "zoom_attendant",
    "attendant": "attendant",
    "microphone": "microphone",
    "mic": "microphone",
}

CATEGORY_LABELS_PT: Dict[str, str] = {
    "chairman": "Presidente",
    "auxiliary_counselor": "Conselheiro auxiliar",
    "opening_prayer": "Oração inicial",
    "closing_prayer": "Oração final",
    "treasures_talk": "Tesouros (discurso)",
    "spiritual_gems": "Joias espirituais",
    "bible_reading": "Leitura da Bíblia",
    "school_overseer": "Superintendente da escola",
    "apply1": "Aplique-se — parte 1",
    "apply2": "Aplique-se — parte 2",
    "apply3": "Aplique-se — parte 3",
    "apply4": "Aplique-se — parte 4",
    "apply1_assistant": "Aplique-se — assistente 1",
    "apply2_assistant": "Aplique-se — assistente 2",
    "apply3_assistant": "Aplique-se — assistente 3",
    "apply4_assistant": "Aplique-se — assistente 4",
    "living1": "Vida cristã — parte 1",
    "living2": "Vida cristã — parte 2",
    "living3": "Vida cristã — parte 3",
    "cbs": "Estudo bíblico (condutor)",
    "cbs_reader": "Estudo bíblico (leitor)",
    "host": "Anfitrião",
    "cohost": "Coanfitrião",
    "zoom_attendant": "Atendente Zoom",
    "attendant": "Atendente",
    "microphone": "Microfone",
}

# Mapeamento privilégio Hourglass / MSA → categorias do relatório
PRIVILEGE_TO_CATEGORIES: Dict[str, Set[str]] = {
    "chairman": {"chairman"},
    "presidente": {"chairman"},
    "prayer": {"opening_prayer", "closing_prayer"},
    "oracao": {"opening_prayer", "closing_prayer"},
    "opening_prayer": {"opening_prayer"},
    "closing_prayer": {"closing_prayer"},
    "bible_reading": {"bible_reading"},
    "reading": {"bible_reading"},
    "treasures": {"treasures_talk"},
    "treasures_talk": {"treasures_talk"},
    "gems": {"spiritual_gems"},
    "spiritual_gems": {"spiritual_gems"},
    "apply": {"apply1", "apply2", "apply3", "apply4"},
    "apply_assistant": {"apply1_assistant", "apply2_assistant", "apply3_assistant", "apply4_assistant"},
    "living": {"living1", "living2", "living3"},
    "cbs": {"cbs"},
    "cbs_reader": {"cbs_reader"},
    "auxiliary": {"auxiliary_counselor"},
    "auxiliary_counselor": {"auxiliary_counselor"},
    "school_overseer": {"school_overseer"},
    "host": {"host", "cohost"},
    "attendant": {"attendant", "zoom_attendant"},
    "microphone": {"microphone"},
}

USER_OBJECT_HINTS = frozenset(
    {
        "id",
        "user_id",
        "publisher_id",
        "assignee_id",
        "person_id",
        "first_name",
        "last_name",
        "display_name",
        "name",
        "full_name",
    }
)

PART_TYPE_MAP = {
    "chairman": "chairman",
    "auxiliarycounselor": "auxiliary_counselor",
    "openingprayer": "opening_prayer",
    "closingprayer": "closing_prayer",
    "treasurestalk": "treasures_talk",
    "gems": "spiritual_gems",
    "biblereading": "bible_reading",
    "apply1": "apply1",
    "apply2": "apply2",
    "apply3": "apply3",
    "apply4": "apply4",
    "apply1assistant": "apply1_assistant",
    "apply2assistant": "apply2_assistant",
    "apply3assistant": "apply3_assistant",
    "apply4assistant": "apply4_assistant",
    "living1": "living1",
    "living2": "living2",
    "living3": "living3",
    "cbs": "cbs",
    "cbsreader": "cbs_reader",
    "host": "host",
    "cohost": "cohost",
    "zoomattendant": "zoom_attendant",
}


def _norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")


def _slug_privilege(name: str) -> str:
    return _norm_key(name)


def load_json(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        sys.exit(f"Erro ao ler {path}: {exc}")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        sys.exit(f"JSON inválido em {path}: {exc}")


def extract_schedule_roots(payload: Any) -> List[Any]:
    """Retorna lista de entradas semanais (dicts) a partir de vários formatos de export."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, (dict, list))]
    if not isinstance(payload, dict):
        return []

    for key in ("schedules", "schedule", "data", "items", "weeks"):
        val = payload.get(key)
        if isinstance(val, list):
            return val
        if isinstance(val, dict):
            return list(val.values())

    # Um único objeto de semana
    if payload.get("date") or payload.get("chairman") is not None:
        return [payload]

    return []


def publisher_label(raw: Any, id_names: Dict[str, str]) -> Optional[str]:
    """Converte valor de designação em etiqueta estável para contagem."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        if int(raw) == 0:
            return None
        key = str(int(raw))
        return id_names.get(key, f"id:{key}")
    if isinstance(raw, str):
        s = raw.strip()
        if not s or s.lower() in ("null", "none", "0"):
            return None
        if s.isdigit():
            return id_names.get(s, f"id:{s}")
        return s
    if isinstance(raw, dict):
        for id_field in ("user_id", "publisher_id", "assignee_id", "person_id", "id"):
            if id_field in raw and raw[id_field] is not None:
                key = str(raw[id_field]).strip()
                if key:
                    name = _name_from_dict(raw)
                    if name:
                        id_names[key] = name
                    return id_names.get(key, f"id:{key}")
        name = _name_from_dict(raw)
        if name:
            return name
        return None
    if isinstance(raw, list):
        labels = [publisher_label(x, id_names) for x in raw]
        labels = [x for x in labels if x]
        return ", ".join(labels) if labels else None
    return str(raw)


def _name_from_dict(d: Dict[str, Any]) -> Optional[str]:
    for field in ("descriptor", "display_name", "full_name", "name"):
        v = d.get(field)
        if isinstance(v, str) and v.strip():
            return v.strip()
    fn = d.get("first_name") or d.get("firstName") or d.get("firstname") or ""
    ln = d.get("last_name") or d.get("lastName") or d.get("lastname") or ""
    if isinstance(fn, str) and isinstance(ln, str):
        combined = f"{fn.strip()} {ln.strip()}".strip()
        if combined:
            return combined
    return None


def categorize_field_key(key: str) -> Optional[str]:
    nk = _norm_key(key)
    if nk in SKIP_KEYS or nk.endswith("_id") and nk[:-3] in SKIP_KEYS:
        return None
    if nk in ROLE_ALIASES:
        return ROLE_ALIASES[nk]
    m = re.match(r"apply(\d)(_assistant|assistant)?", nk)
    if m:
        num = m.group(1)
        if m.group(2):
            return f"apply{num}_assistant"
        return f"apply{num}"
    m = re.match(r"living(\d)", nk)
    if m:
        return f"living{m.group(1)}"
    if nk in ("prayer", "prayers"):
        return None  # genérico — tratar em filhos
    return ROLE_ALIASES.get(nk)


def categorize_part_type(value: str) -> Optional[str]:
    compact = re.sub(r"[^a-z0-9]", "", value.lower())
    return PART_TYPE_MAP.get(compact)


def index_publishers_from_schedules(weeks: Iterable[Any], id_names: Dict[str, str]) -> None:
    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            if USER_OBJECT_HINTS.intersection(obj.keys()):
                label = publisher_label(obj, id_names)
                for id_field in ("user_id", "publisher_id", "id", "assignee_id"):
                    if id_field in obj and obj[id_field] is not None:
                        id_names[str(obj[id_field])] = label or id_names.get(str(obj[id_field]), "")
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    for week in weeks:
        walk(week)


def record_assignment(
    counts: DefaultDict[str, DefaultDict[str, int]],
    category: str,
    person: Optional[str],
) -> None:
    if not person or not category:
        return
    counts[category][person] += 1


HOURGLASS_SECTIONS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("tgw", ("treasures_talk", "spiritual_gems", "bible_reading")),
    ("fm", ("apply1", "apply2", "apply3", "apply4")),
    ("lac", ("living1", "cbs")),
)


def _walk_hourglass_sections(week: Dict[str, Any], counts: DefaultDict[str, DefaultDict[str, int]], id_names: Dict[str, str]) -> None:
    """Hourglass schedule: assignee/assistant em listas tgw, fm, lac."""
    for section, categories in HOURGLASS_SECTIONS:
        items = week.get(section)
        if not isinstance(items, list):
            continue
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            cat = categories[idx] if idx < len(categories) else f"{section}_{idx + 1}"
            record_assignment(counts, cat, publisher_label(item.get("assignee"), id_names))
            assistant = item.get("assistant")
            if assistant:
                asst_cat = f"{cat}_assistant" if cat.startswith("apply") else "apply_assistant"
                if cat.startswith("apply"):
                    asst_cat = f"{cat}_assistant"
                elif section == "fm":
                    asst_cat = f"apply{idx + 1}_assistant" if idx < 4 else "fm_assistant"
                else:
                    asst_cat = f"{section}_assistant"
                record_assignment(counts, asst_cat, publisher_label(assistant, id_names))


def walk_week(
    obj: Any,
    counts: DefaultDict[str, DefaultDict[str, int]],
    id_names: Dict[str, str],
    context_key: Optional[str] = None,
    depth: int = 0,
) -> None:
    if depth > 12:
        return
    if isinstance(obj, list):
        for item in obj:
            walk_week(item, counts, id_names, context_key, depth + 1)
        return
    if not isinstance(obj, dict):
        return

    part_type = obj.get("part_type") or obj.get("partType") or obj.get("type") or obj.get("role")
    if isinstance(part_type, str):
        cat = categorize_part_type(part_type)
        if cat:
            for assignee_key in (
                "user",
                "assignee",
                "publisher",
                "person",
                "user_id",
                "publisher_id",
                "assignee_id",
            ):
                if assignee_key in obj:
                    record_assignment(counts, cat, publisher_label(obj[assignee_key], id_names))
            if "id" in obj and any(k in obj for k in USER_OBJECT_HINTS):
                record_assignment(counts, cat, publisher_label(obj, id_names))

    for key, value in obj.items():
        nk = _norm_key(key)
        if nk in SKIP_KEYS:
            continue
        cat = categorize_field_key(key)
        if cat and not isinstance(value, (dict, list)):
            record_assignment(counts, cat, publisher_label(value, id_names))
        elif cat and isinstance(value, dict):
            record_assignment(counts, cat, publisher_label(value, id_names))
        elif isinstance(value, dict) and USER_OBJECT_HINTS.intersection(value.keys()):
            use_cat = cat or context_key
            if use_cat:
                record_assignment(counts, use_cat, publisher_label(value, id_names))
        elif key in ("parts", "assignments", "slots", "schools", "items", "children"):
            walk_week(value, counts, id_names, context_key or cat, depth + 1)
        elif isinstance(value, (dict, list)):
            walk_week(value, counts, id_names, cat or context_key, depth + 1)


def parse_schedules(payload: Any) -> Tuple[DefaultDict[str, DefaultDict[str, int]], Dict[str, str], int]:
    weeks = extract_schedule_roots(payload)
    id_names: Dict[str, str] = {}
    index_publishers_from_schedules(weeks, id_names)
    counts: DefaultDict[str, DefaultDict[str, int]] = defaultdict(lambda: defaultdict(int))
    week_count = 0
    for week in weeks:
        if isinstance(week, dict):
            week_count += 1
            _walk_hourglass_sections(week, counts, id_names)
            walk_week(week, counts, id_names, None, 0)
        elif isinstance(week, list):
            for sub in week:
                if isinstance(sub, dict):
                    week_count += 1
                    walk_week(sub, counts, id_names, None, 0)
    return counts, id_names, week_count


def parse_privileges(payload: Any) -> Tuple[Dict[str, str], Dict[str, Set[str]]]:
    """
    Retorna (id→nome, categoria→set de ids elegíveis).
    """
    names: Dict[str, str] = {}
    eligible: Dict[str, Set[str]] = defaultdict(set)

    def add_user(uid: str, name: str, privs: Iterable[Any]) -> None:
        if not uid:
            return
        if name:
            names[uid] = name
        for p in privs:
            if p is None:
                continue
            if isinstance(p, bool):
                continue
            if isinstance(p, dict):
                pname = p.get("name") or p.get("key") or p.get("id")
                if pname:
                    add_user(uid, name, [pname])
                continue
            slug = _slug_privilege(str(p))
            if not slug:
                continue
            cats = PRIVILEGE_TO_CATEGORIES.get(slug, {slug} if slug in CATEGORY_LABELS_PT else set())
            if not cats and slug in ROLE_ALIASES:
                cats = {ROLE_ALIASES[slug]}
            for cat in cats:
                eligible[cat].add(uid)

    def walk_users(seq: Iterable[Any]) -> None:
        for u in seq:
            if not isinstance(u, dict):
                continue
            uid = None
            for id_field in ("id", "user_id", "publisher_id"):
                if u.get(id_field) is not None:
                    uid = str(u[id_field])
                    break
            if not uid:
                continue
            name = _name_from_dict(u) or names.get(uid, f"id:{uid}")
            names[uid] = name
            privs = u.get("privileges") or u.get("scheduling_privileges") or u.get("permissions") or []
            if isinstance(privs, dict):
                for k, enabled in privs.items():
                    if enabled:
                        add_user(uid, name, [k])
            elif isinstance(privs, list):
                add_user(uid, name, privs)

    def walk_hourglass_privilege_map(priv_map: Dict[str, Any]) -> None:
        """Formato Hourglass: { apply1: [uid, ...], chairman: [...] }."""
        for cat, uids in priv_map.items():
            if not isinstance(uids, list):
                continue
            for raw in uids:
                if isinstance(raw, bool):
                    continue
                try:
                    uid = str(int(raw))
                except (TypeError, ValueError):
                    continue
                nm = names.get(uid, f"id:{uid}")
                add_user(uid, nm, [cat])

    if isinstance(payload, list):
        walk_users(payload)
    elif isinstance(payload, dict):
        for key in ("users", "publishers", "privileges", "data"):
            val = payload.get(key)
            if isinstance(val, list):
                walk_users(val)
            elif isinstance(val, dict) and key == "privileges":
                walk_hourglass_privilege_map(val)
        if payload.get("id") and payload.get("privileges"):
            walk_users([payload])
        if not names and not eligible:
            lists_only = [
                v for v in payload.values() if isinstance(v, list) and v and not isinstance(v[0], dict)
            ]
            if lists_only and not any(k in payload for k in ("users", "publishers", "data")):
                walk_hourglass_privilege_map(payload)
    return names, eligible


def parse_users(payload: Any) -> Dict[str, str]:
    """Mapeia id → nome (scheduling/users, fsreport/startup, lista de publicadores)."""
    names: Dict[str, str] = {}

    def record(obj: Dict[str, Any]) -> None:
        uid = None
        for id_field in ("id", "user_id", "publisher_id"):
            if obj.get(id_field) is not None:
                try:
                    uid = str(int(obj[id_field]))
                except (TypeError, ValueError):
                    uid = str(obj[id_field])
                break
        if not uid or uid == "0":
            return
        label = _name_from_dict(obj)
        if label:
            names[uid] = label

    def walk(obj: Any, depth: int = 0) -> None:
        if depth > 10:
            return
        if isinstance(obj, list):
            for item in obj:
                walk(item, depth + 1)
        elif isinstance(obj, dict):
            if USER_OBJECT_HINTS.intersection(obj.keys()) or (
                obj.get("id") is not None and (obj.get("descriptor") or obj.get("firstname"))
            ):
                record(obj)
            for val in obj.values():
                walk(val, depth + 1)

    walk(payload)
    return names


def merge_eligible_for_category(
    category: str,
    counts: Dict[str, int],
    priv_names: Dict[str, str],
    eligible_by_cat: Dict[str, Set[str]],
    id_names: Dict[str, str],
) -> Set[str]:
    """Nomes (labels) elegíveis para a categoria, quando privilégios existem."""
    ids = eligible_by_cat.get(category)
    if not ids:
        return set()
    labels: Set[str] = set()
    for uid in ids:
        nm = priv_names.get(uid) or id_names.get(uid, f"id:{uid}")
        labels.add(nm)
    return labels


def format_report(
    counts: DefaultDict[str, DefaultDict[str, int]],
    week_count: int,
    schedule_path: Path,
    priv_path: Optional[Path],
    priv_names: Dict[str, str],
    eligible_by_cat: Dict[str, Set[str]],
    id_names: Dict[str, str],
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: List[str] = [
        "# Relatório de rodízio — designações (meio de semana)",
        "",
        f"- **Gerado em:** {now}",
        f"- **Schedule:** `{schedule_path}`",
        f"- **Semanas analisadas:** {week_count}",
    ]
    if priv_path:
        lines.append(f"- **Privilégios:** `{priv_path}`")
    else:
        lines.append("- **Privilégios:** não fornecidos (sem filtro de elegibilidade)")
    if id_names and any(not k.startswith("id:") for k in id_names.values()):
        lines.append("- **Nomes:** carregados (users/privileges)")
    lines.extend(["", "---", ""])

    if week_count == 0:
        lines.append(
            "Nenhuma semana reconhecida no JSON. Verifique o formato (array ou chave `schedules`) "
            "em `internal/hourglass-schedule-schema-notes.md`."
        )
        return "\n".join(lines) + "\n"

    categories = sorted(counts.keys(), key=lambda c: CATEGORY_LABELS_PT.get(c, c))
    if not categories:
        lines.append(
            "Nenhuma designação contada. O payload pode usar chaves não mapeadas — "
            "consulte as notas de schema ou envie um exemplo anonimizado."
        )
        return "\n".join(lines) + "\n"

    for cat in categories:
        label = CATEGORY_LABELS_PT.get(cat, cat.replace("_", " ").title())
        per_person = counts[cat]
        eligible_labels = merge_eligible_for_category(
            cat, per_person, priv_names, eligible_by_cat, id_names
        )
        min_c = min(per_person.values()) if per_person else 0
        max_c = max(per_person.values()) if per_person else 0
        lines.append(f"## {label}")
        lines.append("")
        lines.append(f"Contagens (min={min_c}, max={max_c}, participantes={len(per_person)}).")
        lines.append("")

        rows: List[Tuple[str, int, str]] = []
        for person, n in per_person.items():
            note = ""
            if eligible_labels:
                if person in eligible_labels and n == min_c:
                    note = "candidato (menor entre elegíveis)"
                elif person in eligible_labels:
                    note = "elegível"
                elif n == min_c:
                    note = "menor contagem (verificar elegibilidade)"
            elif n == min_c:
                note = "menor contagem"
            rows.append((person, n, note))

        rows.sort(key=lambda r: (r[1], r[0].lower()))

        if eligible_labels:
            elig_counts = [(p, per_person.get(p, 0)) for p in eligible_labels]
            if elig_counts:
                min_elig = min(c for _, c in elig_counts)
                candidates = sorted([p for p, c in elig_counts if c == min_elig])
                lines.append(
                    f"**Sugestão (elegíveis com menor contagem = {min_elig}):** "
                    + ", ".join(candidates)
                )
                lines.append("")

        lines.append("| Publicador | Designações | Nota |")
        lines.append("|------------|------------:|------|")

        for person, n, note in rows:
            lines.append(f"| {person} | {n} | {note} |")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Relatório de rodízio Hourglass (stdlib).")
    parser.add_argument("--schedule", required=True, type=Path, help="JSON do schedule (ou export combinado)")
    parser.add_argument("--privileges", type=Path, default=None, help="JSON de privilégios (opcional)")
    parser.add_argument("--users", type=Path, default=None, help="JSON de publicadores (GET scheduling/users)")
    parser.add_argument("--out", type=Path, default=None, help="Arquivo markdown de saída (default: stdout)")
    args = parser.parse_args()

    schedule_payload = load_json(args.schedule)
    counts, id_names, week_count = parse_schedules(schedule_payload)

    priv_names: Dict[str, str] = {}
    eligible_by_cat: Dict[str, Set[str]] = {}
    users_path: Optional[Path] = args.users
    if args.users:
        user_names = parse_users(load_json(args.users))
        for uid, nm in user_names.items():
            if nm:
                id_names[uid] = nm
    if args.privileges:
        priv_payload = load_json(args.privileges)
        priv_names, eligible_by_cat = parse_privileges(priv_payload)
        for uid, nm in priv_names.items():
            if nm and uid not in id_names:
                id_names[uid] = nm

    # Recontar labels nos counts (substituir id:NNNN por nome quando id_names existe)
    if id_names:
        new_counts: DefaultDict[str, DefaultDict[str, int]] = defaultdict(lambda: defaultdict(int))
        for cat, per in counts.items():
            for person, n in per.items():
                if person.startswith("id:"):
                    uid = person[3:]
                    person = id_names.get(uid, person)
                new_counts[cat][person] += n
        counts = new_counts

    report = format_report(
        counts,
        week_count,
        args.schedule,
        args.privileges,
        priv_names,
        eligible_by_cat,
        id_names,
    )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        print(f"Relatório escrito em {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(report)


if __name__ == "__main__":
    main()
