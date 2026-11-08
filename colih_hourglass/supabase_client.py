from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .config import Settings


class SupabaseClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base = f"{settings.supabase_url}/rest/v1"

    def _headers(self, prefer: Optional[str] = None) -> Dict[str, str]:
        h = {
            "apikey": self.settings.supabase_key,
            "Authorization": f"Bearer {self.settings.supabase_key}",
            "Content-Type": "application/json",
        }
        if prefer:
            h["Prefer"] = prefer
        return h

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: str = "",
        body: Any = None,
        prefer: Optional[str] = None,
    ) -> Any:
        url = f"{self.base}/{path}{query}"
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        req = Request(url, data=data, method=method, headers=self._headers(prefer))
        try:
            with urlopen(req, timeout=120) as resp:
                raw = resp.read().decode("utf-8")
                if not raw:
                    return None
                return json.loads(raw)
        except HTTPError as exc:
            err = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Supabase {method} {path}: HTTP {exc.code} — {err}") from exc

    def select(
        self,
        table: str,
        *,
        filters: Optional[str] = None,
        order: Optional[str] = None,
        limit: Optional[int] = None,
        columns: str = "*",
    ) -> List[Dict[str, Any]]:
        q = f"?select={quote(columns, safe='*,()')}"
        if filters:
            q += f"&{filters}"
        if order:
            q += f"&order={order}"
        if limit is not None:
            q += f"&limit={limit}"
        result = self._request("GET", table, query=q)
        return result if isinstance(result, list) else []

    def upsert(self, table: str, rows: List[Dict[str, Any]], on_conflict: str) -> List[Dict[str, Any]]:
        if not rows:
            return []
        q = f"?on_conflict={quote(on_conflict, safe=',')}"
        return self._request(
            "POST",
            table,
            query=q,
            body=rows,
            prefer="resolution=merge-duplicates,return=representation",
        )

    def insert(self, table: str, row: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self._request("POST", table, body=row, prefer="return=representation")

    def patch(self, table: str, filters: str, row: Dict[str, Any]) -> List[Dict[str, Any]]:
        q = f"?{filters}"
        return self._request("PATCH", table, query=q, body=row, prefer="return=representation")

    def congregation_id_for_lgroup(self, lgroup: int) -> str:
        rows = self.select("congregations", filters=f"lgroup=eq.{lgroup}", limit=1, columns="id,lgroup")
        if rows:
            return str(rows[0]["id"])
        created = self.insert("congregations", {"lgroup": lgroup})
        return str(created[0]["id"])
