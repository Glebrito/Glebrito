from __future__ import annotations

import cgi
import html
import io
import json
import tempfile
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .config import DEFAULT_LGROUP, Settings
from .rules_engine import SISTER_FM_CATEGORIES
from .sync import import_rotation_file

# Estado em memória (uso local, um coordenador por processo)
_state: Dict[str, Any] = {
    "last_suggestion": None,
    "last_import_result": None,
    "last_import_at": None,
    "last_error": None,
}

HOURGLASS_ORIGIN = "https://app.hourglass-app.com"

SNIPPET_STEPS = (
    "1. Inicie o painel: <code>scripts\\iniciar-painel.bat</code> (ou "
    "<code>python -m colih_hourglass serve --env-file scripts\\hourglass.env</code>).<br>"
    "2. No Hourglass logado, DevTools → <strong>Sources → Snippets</strong> → cole "
    "<code>scripts/hourglass-browser-export-snippet.js</code> → <strong>Run</strong>.<br>"
    "3. O snippet envia para <code>http://127.0.0.1:8765/import-json</code> e importa no Supabase."
)

ROLE_LABELS_PT: Dict[str, str] = {
    "chairman": "Presidente",
    "opening_prayer": "Oração inicial",
    "closing_prayer": "Oração final",
    "treasures_talk": "Tesouros da Palavra",
    "spiritual_gems": "Joias espirituais",
    "bible_reading": "Leitura da Bíblia",
    "apply1": "Parte 1 — Aplique",
    "apply1_assistant": "Parte 1 — Assistente",
    "apply2": "Parte 2 — Aplique",
    "apply2_assistant": "Parte 2 — Assistente",
    "apply3": "Parte 3 — Aplique",
    "apply3_assistant": "Parte 3 — Assistente",
    "apply4": "Parte 4 — Aplique",
    "apply4_assistant": "Parte 4 — Assistente",
    "living1": "Nossa vida cristã 1",
    "living2": "Nossa vida cristã 2",
    "living3": "Nossa vida cristã 3",
    "cbs": "Estudo bíblico de congregação",
    "cbs_reader": "Leitor do EBC",
    "auxiliary_counselor": "Conselheiro auxiliar",
}


def env_status() -> Dict[str, Any]:
    import os

    keys = {
        "SUPABASE_URL": bool(os.environ.get("SUPABASE_URL")),
        "SUPABASE_SERVICE_ROLE_KEY": bool(os.environ.get("SUPABASE_SERVICE_ROLE_KEY")),
        "SUPABASE_KEY": bool(os.environ.get("SUPABASE_KEY")),
        "SUPABASE_ANON_KEY": bool(os.environ.get("SUPABASE_ANON_KEY")),
        "HOURGLASS_LGROUP": os.environ.get("HOURGLASS_LGROUP") or str(DEFAULT_LGROUP),
    }
    has_key = (
        keys["SUPABASE_SERVICE_ROLE_KEY"]
        or keys["SUPABASE_KEY"]
        or keys["SUPABASE_ANON_KEY"]
    )
    return {
        "supabase_configured": keys["SUPABASE_URL"] and has_key,
        "vars": keys,
        "lgroup": int(os.environ.get("HOURGLASS_LGROUP", DEFAULT_LGROUP)),
    }


def panel_public_status() -> Dict[str, Any]:
    """JSON para /api/status e feedback do snippet."""
    st = env_status()
    last = _state.get("last_import_result")
    return {
        "ok": True,
        "supabase_configured": st["supabase_configured"],
        "lgroup": st["lgroup"],
        "last_import_at": _state.get("last_import_at"),
        "last_import": {
            "status": last.get("status") if isinstance(last, dict) else None,
            "stats": last.get("stats") if isinstance(last, dict) else None,
        }
        if last
        else None,
        "last_suggestion_week": (_state.get("last_suggestion") or {}).get("week"),
        "last_error": _state.get("last_error"),
    }


def _try_settings() -> Tuple[Optional[Settings], Optional[str]]:
    import os

    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_KEY")
        or os.environ.get("SUPABASE_ANON_KEY")
    )
    if not key:
        return None, "Defina SUPABASE_SERVICE_ROLE_KEY (ou SUPABASE_ANON_KEY) no ambiente ou em --env-file."
    try:
        return Settings.from_env(), None
    except SystemExit as exc:
        return None, str(exc)


def _default_week() -> str:
    today = datetime.utcnow().date()
    if today.weekday() == 0:
        return today.isoformat()
    return (today + timedelta(days=(7 - today.weekday()))).isoformat()


def _format_last_import() -> str:
    if not _state.get("last_import_result"):
        return "Nenhuma importação nesta sessão — rode o snippet no Hourglass."
    at = _state.get("last_import_at") or ""
    res = _state["last_import_result"]
    stats = res.get("stats") if isinstance(res, dict) else res
    status = res.get("status") if isinstance(res, dict) else "ok"
    when = html.escape(at[:19].replace("T", " ") if at else "agora")
    return f"Última importação: <strong>{html.escape(str(status))}</strong> ({when}) — {html.escape(str(stats))}"


def import_json_body(raw: bytes) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Importa JSON bruto; retorna (resultado, mensagem_de_erro)."""
    settings, err = _try_settings()
    if err or not settings:
        return None, err
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"JSON inválido: {exc}"
    suffix = ".json"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        tmp_path = Path(tmp.name)
    try:
        result = import_rotation_file(settings, tmp_path)
        _state["last_import_result"] = result
        _state["last_import_at"] = datetime.utcnow().isoformat() + "Z"
        _state["last_error"] = None
        return result, None
    except Exception as exc:
        _state["last_error"] = str(exc)
        return None, str(exc)
    finally:
        tmp_path.unlink(missing_ok=True)


def _page(
    status: Dict[str, Any],
    message: Optional[str] = None,
    error: Optional[str] = None,
    suggestions: Optional[Dict[str, Any]] = None,
) -> bytes:
    cfg = "ok" if status["supabase_configured"] else "warn"
    cfg_text = (
        "Supabase pronto"
        if status["supabase_configured"]
        else "Configure SUPABASE_URL e chave em hourglass.env"
    )
    rows_html = ""
    if suggestions and suggestions.get("suggestions"):
        for s in suggestions["suggestions"]:
            role = s.get("role_category", "")
            is_apply = role in SISTER_FM_CATEGORIES
            tr_class = ' class="apply-sister"' if is_apply else ""
            name = html.escape(str(s.get("display_name") or "—"))
            uid = html.escape(str(s.get("hourglass_user_id") or "—"))
            st = html.escape(str(s.get("status") or ""))
            label = html.escape(ROLE_LABELS_PT.get(role, role))
            rows_html += (
                f"<tr{tr_class}><td>{label}</td><td class='name'>{name}</td>"
                f"<td class='uid'>{uid}</td><td>{st}</td></tr>"
            )
    else:
        rows_html = (
            '<tr><td colspan="4" class="empty">Importe do Hourglass e gere sugestões abaixo.</td></tr>'
        )

    msg_block = ""
    if message:
        msg_block += f'<div class="banner ok" role="status">{html.escape(message)}</div>'
    if error:
        msg_block += f'<div class="banner err" role="alert">{html.escape(error)}</div>'

    week_val = html.escape((suggestions or {}).get("week") or _default_week())
    import_line = _format_last_import()

    body = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Colih — Rodízio Hourglass</title>
  <style>
    :root {{
      --bg: #f0f2f5;
      --card: #fff;
      --text: #1c1e21;
      --muted: #5c6370;
      --accent: #2563eb;
      --accent-hover: #1d4ed8;
      --ok: #15803d;
      --warn: #b45309;
      --err: #b91c1c;
      --border: #e5e7eb;
      --radius: 12px;
      font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
      line-height: 1.5;
      color: var(--text);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      min-height: 100vh;
    }}
    .wrap {{
      max-width: 56rem;
      margin: 0 auto;
      padding: 1.5rem 1.25rem 2.5rem;
    }}
    header {{
      margin-bottom: 1.25rem;
    }}
    header h1 {{
      margin: 0 0 0.35rem;
      font-size: 1.5rem;
      font-weight: 650;
      letter-spacing: -0.02em;
    }}
    header p {{
      margin: 0;
      color: var(--muted);
      font-size: 0.92rem;
    }}
    .grid {{
      display: grid;
      gap: 1rem;
    }}
    @media (min-width: 720px) {{
      .grid-2 {{ grid-template-columns: 1fr 1fr; }}
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1.15rem 1.25rem;
      box-shadow: 0 1px 2px rgba(0,0,0,.04);
    }}
    .card h2 {{
      margin: 0 0 0.65rem;
      font-size: 1.05rem;
      font-weight: 600;
    }}
    .card.primary {{
      border-color: #bfdbfe;
      background: linear-gradient(180deg, #eff6ff 0%, #fff 55%);
    }}
    .pill {{
      display: inline-block;
      font-size: 0.75rem;
      font-weight: 600;
      padding: 0.2rem 0.55rem;
      border-radius: 999px;
      margin-bottom: 0.5rem;
    }}
    .pill.ok {{ background: #dcfce7; color: var(--ok); }}
    .pill.warn {{ background: #fef3c7; color: var(--warn); }}
    .steps {{
      font-size: 0.9rem;
      color: var(--text);
      line-height: 1.55;
    }}
    .steps code {{
      background: #f3f4f6;
      padding: 0.1rem 0.35rem;
      border-radius: 4px;
      font-size: 0.85em;
    }}
    .import-status {{
      margin-top: 0.75rem;
      padding: 0.65rem 0.75rem;
      background: #f9fafb;
      border-radius: 8px;
      font-size: 0.88rem;
      color: var(--muted);
    }}
    label {{ display: block; margin-top: 0.5rem; font-size: 0.9rem; font-weight: 500; }}
    input[type=date] {{
      margin: 0.35rem 0 0.75rem;
      padding: 0.45rem 0.6rem;
      border: 1px solid var(--border);
      border-radius: 8px;
      font-size: 1rem;
      width: 100%;
      max-width: 14rem;
    }}
    input[type=file] {{
      margin: 0.35rem 0 0.75rem;
      font-size: 0.88rem;
    }}
    .btn {{
      display: inline-block;
      margin-top: 0.5rem;
      padding: 0.55rem 1.1rem;
      background: var(--accent);
      color: #fff;
      border: none;
      border-radius: 8px;
      font-size: 0.95rem;
      font-weight: 600;
      cursor: pointer;
    }}
    .btn:hover {{ background: var(--accent-hover); }}
    .btn-secondary {{
      background: #fff;
      color: var(--accent);
      border: 1px solid var(--border);
    }}
    .banner {{
      padding: 0.75rem 1rem;
      border-radius: 8px;
      margin-bottom: 1rem;
      font-size: 0.92rem;
    }}
    .banner.ok {{ background: #dcfce7; color: #14532d; }}
    .banner.err {{ background: #fee2e2; color: #7f1d1d; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.9rem;
    }}
    th, td {{
      padding: 0.5rem 0.6rem;
      text-align: left;
      border-bottom: 1px solid var(--border);
    }}
    th {{
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.03em;
      color: var(--muted);
      font-weight: 600;
    }}
    td.name {{ font-weight: 500; }}
    td.uid {{ color: var(--muted); font-size: 0.82rem; }}
    tr.apply-sister {{ background: #fffbeb; }}
    tr.apply-sister td.name {{ color: #92400e; }}
    .empty {{ color: var(--muted); font-style: italic; }}
    .meta {{
      font-size: 0.82rem;
      color: var(--muted);
      margin-top: 0.75rem;
    }}
    .meta a {{ color: var(--accent); }}
    details {{
      margin-top: 1rem;
      font-size: 0.88rem;
      color: var(--muted);
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <h1>Colih — Rodízio Hourglass</h1>
      <p>Servidor local em <strong>127.0.0.1</strong> · lgroup {html.escape(str(status["lgroup"]))}</p>
    </header>

    {msg_block}

    <div class="grid">
      <section class="card primary" aria-labelledby="upd-head">
        <span class="pill {'ok' if cfg == 'ok' else 'warn'}">{html.escape(cfg_text)}</span>
        <h2 id="upd-head">Atualizar dados do Hourglass</h2>
        <div class="steps">{SNIPPET_STEPS}</div>
        <div class="import-status">{import_line}</div>
      </section>

      <section class="card" aria-labelledby="sug-head">
        <h2 id="sug-head">Sugerir próxima semana</h2>
        <form method="post" action="/suggest">
          <label for="week">Segunda-feira (AAAA-MM-DD)</label>
          <input id="week" name="week" type="date" value="{week_val}" required>
          <label class="chk"><input type="checkbox" name="persist" value="1"> Gravar rascunho no Supabase</label>
          <p><button type="submit" class="btn">Gerar sugestões</button></p>
        </form>
        <p class="meta">
          <a href="/download/sugestao.json">sugestao.json</a>
          ·
          <a href="/download/draft.json?week={week_val}">draft da semana</a>
        </p>
      </section>
    </div>

    <section class="card" style="margin-top:1rem" aria-labelledby="tbl-head">
      <h2 id="tbl-head">Sugestões</h2>
      <p class="meta">Nomes vêm do Supabase (members + histórico). Destaque: partes 1–3 e assistentes (irmãs).</p>
      <table>
        <thead>
          <tr><th>Parte</th><th>Nome</th><th>ID</th><th>Status</th></tr>
        </thead>
        <tbody>
          {rows_html}
        </tbody>
      </table>
    </section>

    <section class="card" style="margin-top:1rem">
      <details>
        <summary>Importar arquivo JSON manualmente (fallback)</summary>
        <form method="post" action="/import" enctype="multipart/form-data" style="margin-top:0.75rem">
          <label for="file">mm-export.json</label>
          <input id="file" name="file" type="file" accept=".json,application/json" required>
          <button type="submit" class="btn btn-secondary">Enviar arquivo</button>
        </form>
      </details>
    </section>
  </div>
</body>
</html>"""
    return body.encode("utf-8")


class PanelHandler(BaseHTTPRequestHandler):
    server_version = "ColihHourglass/0.2"

    def log_message(self, format: str, *args: Any) -> None:
        if args and str(args[0]).startswith("5"):
            super().log_message(format, *args)

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", HOURGLASS_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_html(self, body: bytes, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, obj: Any, code: int = 200, *, cors: bool = False) -> None:
        data = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if cors:
            self._cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location: str = "/") -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def do_OPTIONS(self) -> None:
        path = urlparse(self.path).path
        if path in ("/import-json",):
            self.send_response(204)
            self._cors_headers()
            self.end_headers()
            return
        self.send_error(404)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            st = env_status()
            doc = _state.get("last_suggestion")
            err = _state.get("last_error")
            self._send_html(_page(st, error=err, suggestions=doc))
            return
        if path == "/api/status":
            self._send_json(panel_public_status())
            return
        if path == "/download/sugestao.json":
            doc = _state.get("last_suggestion")
            if not doc:
                self._send_json({"error": "Nenhuma sugestão gerada nesta sessão."}, 404)
                return
            self._send_json(doc)
            return
        if path == "/download/draft.json":
            qs = parse_qs(urlparse(self.path).query)
            week = (qs.get("week") or [None])[0]
            if not week:
                self._send_json({"error": "Parâmetro week=AAAA-MM-DD obrigatório."}, 400)
                return
            settings, err = _try_settings()
            if err or not settings:
                self._send_json({"error": err}, 503)
                return
            from .cli import build_draft_export

            try:
                export = build_draft_export(settings, week)
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)
                return
            self._send_json(export)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/import":
            self._handle_import()
            return
        if path == "/import-json":
            self._handle_import_json()
            return
        if path == "/suggest":
            self._handle_suggest()
            return
        self.send_error(404)

    def _handle_import_json(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            self._send_json({"error": "Corpo vazio."}, 400, cors=True)
            return
        if length > 80 * 1024 * 1024:
            self._send_json({"error": "JSON grande demais."}, 413, cors=True)
            return
        raw = self.rfile.read(length)
        result, err = import_json_body(raw)
        if err:
            self._send_json({"ok": False, "error": err}, 400 if "JSON" in err else 503, cors=True)
            return
        self._send_json(
            {
                "ok": True,
                "message": "Importado no Colih",
                "result": result,
                "status": panel_public_status(),
            },
            cors=True,
        )

    def _handle_import(self) -> None:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self.send_error(400, "Esperado multipart/form-data")
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        environ = {
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": content_type,
            "CONTENT_LENGTH": str(length),
        }
        fs = cgi.FieldStorage(fp=io.BytesIO(body), environ=environ, keep_blank_values=True)
        if "file" not in fs:
            st = env_status()
            self._send_html(_page(st, error="Nenhum arquivo enviado."))
            return
        field = fs["file"]
        if not field.file:
            st = env_status()
            self._send_html(_page(st, error="Upload inválido."))
            return
        raw = field.file.read()
        result, err = import_json_body(raw)
        if err:
            st = env_status()
            self._send_html(_page(st, error=err, suggestions=_state.get("last_suggestion")))
            return
        msg = f"Importação concluída: {result.get('status')} — {result.get('stats')}"
        st = env_status()
        self._send_html(_page(st, message=msg, suggestions=_state.get("last_suggestion")))

    def _handle_suggest(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        qs = parse_qs(body)
        week = (qs.get("week") or [""])[0]
        persist = "persist" in qs
        settings, err = _try_settings()
        if err or not settings:
            st = env_status()
            self._send_html(_page(st, error=err))
            return
        from .cli import run_suggest_week

        try:
            doc = run_suggest_week(settings, week=week or None, persist=persist)
            _state["last_suggestion"] = doc
            _state["last_error"] = None
            msg = f"Sugestões geradas para {doc.get('week')}."
            if persist:
                msg += " Rascunho gravado no Supabase."
        except Exception as exc:
            _state["last_error"] = str(exc)
            st = env_status()
            self._send_html(_page(st, error=str(exc), suggestions=_state.get("last_suggestion")))
            return
        st = env_status()
        self._send_html(_page(st, message=msg, suggestions=doc))


def run_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("Por segurança, o painel só pode escutar em 127.0.0.1 (ou localhost).")
    httpd = ThreadingHTTPServer((host, port), PanelHandler)
    url = f"http://{host}:{port}/"
    print(f"Painel Colih Hourglass em {url}")
    print("POST /import-json — snippet do navegador")
    print("Pressione Ctrl+C para encerrar.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")
    finally:
        httpd.server_close()
