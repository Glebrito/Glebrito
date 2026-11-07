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
    "last_error": None,
}

DOCS_SNIPPET_HINT = (
    "Exporte o JSON do Hourglass no navegador com o snippet "
    "`scripts/hourglass-browser-export-snippet.js` (também em `scripts/` do Agent Store). "
    "Inicie o painel com `scripts/iniciar-painel.bat` (Windows) ou `python -m colih_hourglass serve --env-file`."
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


def _page(
    status: Dict[str, Any],
    message: Optional[str] = None,
    error: Optional[str] = None,
    suggestions: Optional[Dict[str, Any]] = None,
) -> bytes:
    cfg = "ok" if status["supabase_configured"] else "warn"
    cfg_text = (
        "Supabase: variáveis detectadas"
        if status["supabase_configured"]
        else "Supabase: faltam variáveis (configure .env ou --env-file)"
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
                f"<tr{tr_class}><td>{label}</td><td>{name}</td>"
                f"<td>{uid}</td><td>{st}</td></tr>"
            )
    else:
        rows_html = '<tr><td colspan="4">Nenhuma sugestão ainda. Use o formulário abaixo.</td></tr>'

    msg_block = ""
    if message:
        msg_block += f'<p class="msg ok" role="status">{html.escape(message)}</p>'
    if error:
        msg_block += f'<p class="msg err" role="alert">{html.escape(error)}</p>'

    week_val = html.escape((suggestions or {}).get("week") or _default_week())

    body = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Colih — Painel Hourglass</title>
  <style>
    :root {{ font-family: system-ui, sans-serif; line-height: 1.45; color: #1a1a1a; }}
    body {{ max-width: 52rem; margin: 0 auto; padding: 1.25rem; }}
    h1 {{ font-size: 1.35rem; }}
    .panel {{ border: 1px solid #ccc; border-radius: 8px; padding: 1rem; margin: 1rem 0; }}
    .status-{cfg} {{ border-left: 4px solid {'#2a7' if cfg == 'ok' else '#c80'}; }}
    label {{ display: block; margin-top: 0.5rem; }}
    input[type=file], input[type=date] {{ margin: 0.25rem 0 0.75rem; }}
    button {{ padding: 0.45rem 0.9rem; cursor: pointer; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.95rem; }}
    th, td {{ border: 1px solid #ddd; padding: 0.4rem 0.5rem; text-align: left; }}
    th {{ background: #f4f4f4; }}
    tr.apply-sister {{ background: #fff8e6; }}
    .msg.ok {{ color: #164; }}
    .msg.err {{ color: #a00; }}
    .hint {{ font-size: 0.9rem; color: #444; }}
    a {{ color: #06c; }}
  </style>
</head>
<body>
  <h1>Painel local — rodízio Hourglass (Colih)</h1>
  <p class="hint">Servidor apenas em <strong>127.0.0.1</strong>. Não exponha na internet.</p>

  <section class="panel status-{cfg}" aria-labelledby="st-head">
    <h2 id="st-head">Status</h2>
    <p>{html.escape(cfg_text)}</p>
    <ul>
      <li>URL: {"sim" if status["vars"]["SUPABASE_URL"] else "não"}</li>
      <li>Chave de API: {"sim" if status["supabase_configured"] else "não"}</li>
      <li>lgroup padrão: {html.escape(str(status["lgroup"]))}</li>
    </ul>
  </section>

  {msg_block}

  <section class="panel" aria-labelledby="imp-head">
    <h2 id="imp-head">Importar export JSON</h2>
    <p class="hint">{html.escape(DOCS_SNIPPET_HINT)}</p>
    <form method="post" action="/import" enctype="multipart/form-data">
      <label for="file">Arquivo mm-export.json</label>
      <input id="file" name="file" type="file" accept=".json,application/json" required>
      <button type="submit">Enviar e importar</button>
    </form>
  </section>

  <section class="panel" aria-labelledby="sug-head">
    <h2 id="sug-head">Sugerir semana</h2>
    <form method="post" action="/suggest">
      <label for="week">Data da semana (segunda-feira, AAAA-MM-DD)</label>
      <input id="week" name="week" type="date" value="{week_val}" required>
      <label><input type="checkbox" name="persist" value="1"> Gravar rascunho no Supabase</label>
      <p><button type="submit">Gerar sugestões</button></p>
    </form>
    <p>
      <a href="/download/sugestao.json">Baixar última sugestão (sugestao.json)</a>
      ·
      <a href="/download/draft.json?week={week_val}">Baixar rascunho da semana (draft)</a>
    </p>
  </section>

  <section class="panel" aria-labelledby="tbl-head">
    <h2 id="tbl-head">Sugestões</h2>
    <p class="hint">Linhas em destaque: partes 1–3 e assistentes (regra irmãs).</p>
    <table>
      <thead>
        <tr><th>Parte</th><th>Nome</th><th>ID Hourglass</th><th>Status</th></tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
  </section>
</body>
</html>"""
    return body.encode("utf-8")


class PanelHandler(BaseHTTPRequestHandler):
    server_version = "ColihHourglass/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        # Menos ruído no console do coordenador
        if args and str(args[0]).startswith("5"):
            super().log_message(format, *args)

    def _send_html(self, body: bytes, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, obj: Any, code: int = 200) -> None:
        data = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location: str = "/") -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            st = env_status()
            doc = _state.get("last_suggestion")
            err = _state.get("last_error")
            self._send_html(_page(st, error=err, suggestions=doc))
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
        if path == "/suggest":
            self._handle_suggest()
            return
        self.send_error(404)

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
        settings, err = _try_settings()
        if err or not settings:
            st = env_status()
            self._send_html(_page(st, error=err))
            return
        suffix = Path(getattr(field, "filename", None) or "upload.json").suffix or ".json"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(raw)
            tmp_path = Path(tmp.name)
        try:
            result = import_rotation_file(settings, tmp_path)
            _state["last_import_result"] = result
            _state["last_error"] = None
            msg = f"Importação concluída: {result.get('status')} — {result.get('stats')}"
        except Exception as exc:
            _state["last_error"] = str(exc)
            st = env_status()
            self._send_html(_page(st, error=str(exc), suggestions=_state.get("last_suggestion")))
            return
        finally:
            tmp_path.unlink(missing_ok=True)
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
    print("Pressione Ctrl+C para encerrar.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")
    finally:
        httpd.server_close()
