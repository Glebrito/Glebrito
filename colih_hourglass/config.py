from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_LGROUP = 43741
DEFAULT_SUPABASE_URL = "https://xvriolmnmuezzarpwvwn.supabase.co"

STORE_SCRIPTS = Path("/cursor/stores/self/scripts")
DEFAULT_HG_SESSION_PATHS = (
    Path(os.environ.get("HG_SESSION", "")).expanduser() if os.environ.get("HG_SESSION") else None,
    Path("/cursor/stores/self/.hourglass-session.json"),
    STORE_SCRIPTS / ".hourglass-session.json",
)


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_key: str
    lgroup: int
    hg_session_path: Path | None

    @classmethod
    def from_env(cls) -> "Settings":
        url = (os.environ.get("SUPABASE_URL") or DEFAULT_SUPABASE_URL).rstrip("/")
        key = (
            os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
            or os.environ.get("SUPABASE_KEY")
            or os.environ.get("SUPABASE_ANON_KEY")
            or ""
        ).strip()
        if not key:
            raise SystemExit(
                "Defina SUPABASE_SERVICE_ROLE_KEY (recomendado) ou SUPABASE_ANON_KEY no ambiente."
            )
        lgroup = int(os.environ.get("HOURGLASS_LGROUP", DEFAULT_LGROUP))
        hg = None
        for p in DEFAULT_HG_SESSION_PATHS:
            if p and p.is_file():
                hg = p
                break
        return cls(supabase_url=url, supabase_key=key, lgroup=lgroup, hg_session_path=hg)
