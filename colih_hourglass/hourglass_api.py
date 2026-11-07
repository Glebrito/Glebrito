from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen

DEFAULT_BASE = "https://app.hourglass-app.com"
API_VERSION = "/api/v0.2"


def resolve_session_path(explicit: Optional[Path] = None) -> Optional[Path]:
    if explicit and explicit.is_file():
        return explicit
    env = os.environ.get("HG_SESSION", "").strip()
    if env:
        p = Path(env).expanduser()
        if p.is_file():
            return p
    for p in (
        Path("/cursor/stores/self/.hourglass-session.json"),
        Path("/cursor/stores/self/scripts/.hourglass-session.json"),
    ):
        if p.is_file():
            return p
    return None


def load_session(path: Path) -> Dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cookie = (data.get("cookie") or "").strip()
    if not cookie:
        raise RuntimeError(f"Sessão sem cookie: {path}")
    base = (data.get("base") or DEFAULT_BASE).rstrip("/")
    xsrf = (data.get("xsrf") or "").strip()
    if not xsrf:
        for part in cookie.split(";"):
            part = part.strip()
            if part.lower().startswith("x-hourglass-xsrf-token="):
                xsrf = part.split("=", 1)[1].strip()
    return {"cookie": cookie, "xsrf": xsrf, "base": base}


def api_get(session: Dict[str, str], path: str) -> Any:
    url = f"{session['base']}{API_VERSION}{path}"
    headers = {
        "Cookie": session["cookie"],
        "X-Hourglass-XSRF-Token": session["xsrf"],
        "Accept": "application/json",
    }
    req = Request(url, headers=headers, method="GET")
    try:
        with urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 401:
            raise RuntimeError(
                "Hourglass HTTP 401 — sessão expirada. No PC: python hourglass_cli.py session save --curl-file hourglass.curl"
            ) from exc
        raise RuntimeError(f"Hourglass GET {path}: HTTP {exc.code}") from exc


def fetch_schedule(session: Dict[str, str], date_from: str, date_to: str, lgroup: int) -> Any:
    return api_get(session, f"/scheduling/mm/schedule/{date_from}_{date_to}?lgroup={lgroup}")


def fetch_privileges(session: Dict[str, str], lgroup: int) -> Any:
    return api_get(session, f"/scheduling/users/privileges?lgroup={lgroup}")


def fetch_meeting(session: Dict[str, str], date_from: str, date_to: str, lgroup: int) -> Any:
    return api_get(
        session,
        f"/scheduling/mm/meeting/{date_from}_{date_to}?lgroup={lgroup}&no_subs=true",
    )


def load_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
