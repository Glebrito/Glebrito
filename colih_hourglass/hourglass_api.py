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
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def resolve_session_path(explicit: Optional[Path] = None) -> Optional[Path]:
    if explicit and explicit.is_file():
        return explicit
    env = os.environ.get("HG_SESSION", "").strip()
    if env:
        p = Path(env).expanduser()
        if p.is_file():
            return p
    repo_scripts = Path(__file__).resolve().parent.parent / "scripts" / ".hourglass-session.json"
    for p in (
        repo_scripts,
        Path("/cursor/stores/self/.hourglass-session.json"),
        Path("/cursor/stores/self/scripts/.hourglass-session.json"),
    ):
        if p.is_file():
            return p
    return None


def _api_headers(session: Dict[str, str]) -> Dict[str, str]:
    headers = {
        "Cookie": session["cookie"],
        "Accept": "application/json",
        "User-Agent": _USER_AGENT,
        "Origin": DEFAULT_BASE,
        "Referer": f"{DEFAULT_BASE}/v2/page/app/scheduling/mm",
    }
    if session.get("xsrf"):
        headers["X-Hourglass-XSRF-Token"] = session["xsrf"]
    return headers


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


def api_request(
    session: Dict[str, str],
    method: str,
    path: str,
    body: Any = None,
) -> Any:
    url = f"{session['base']}{API_VERSION}{path}"
    data: Optional[bytes] = None
    headers = _api_headers(session)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers = {**headers, "Content-Type": "application/json"}
    req = Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
            if not raw.strip():
                return None
            return json.loads(raw)
    except HTTPError as exc:
        if exc.code == 401:
            raise RuntimeError("Hourglass HTTP 401 — sessão expirada ou inválida.") from exc
        raise RuntimeError(f"Hourglass {method.upper()} {path}: HTTP {exc.code}") from exc


def api_get(session: Dict[str, str], path: str) -> Any:
    return api_request(session, "GET", path)


def api_post(session: Dict[str, str], path: str, body: Any = None) -> Any:
    return api_request(session, "POST", path, body if body is not None else {})


def fetch_schedule(session: Dict[str, str], date_from: str, date_to: str, lgroup: int) -> Any:
    return api_get(session, f"/scheduling/mm/schedule/{date_from}_{date_to}?lgroup={lgroup}")


def fetch_privileges(session: Dict[str, str], lgroup: int) -> Any:
    return api_get(session, f"/scheduling/users/privileges?lgroup={lgroup}")


def fetch_meeting(session: Dict[str, str], date_from: str, date_to: str, lgroup: int) -> Any:
    return api_get(
        session,
        f"/scheduling/mm/meeting/{date_from}_{date_to}?lgroup={lgroup}&no_subs=true",
    )


def fetch_users_directory(session: Dict[str, str], lgroup: int) -> Any:
    """Diretório de publicadores (POST users ou fallback fsreport/startup)."""
    try:
        return api_post(session, f"/scheduling/users?lgroup={lgroup}", {})
    except RuntimeError:
        pass
    try:
        return api_get(session, "/fsreport/startup")
    except RuntimeError:
        return None


def session_setup_help_pt() -> str:
    return (
        "1. Hourglass logado → F12 → Rede → copie cURL para scripts\\hourglass.curl.txt\n"
        "2. python scripts\\hourglass_cli.py session save --curl-file scripts\\hourglass.curl.txt\n"
        "3. Arquivo gerado: scripts\\.hourglass-session.json (ou HG_SESSION apontando para ele)"
    )


def load_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
