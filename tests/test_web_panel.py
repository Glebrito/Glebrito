import json
import os
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from colih_hourglass.env_loader import load_env_file
from colih_hourglass.web_panel import PanelHandler, _page, env_status, panel_public_status
from http.server import ThreadingHTTPServer


class TestEnvLoader(unittest.TestCase):
    def test_load_env_file_does_not_override(self):
        with TemporaryDirectory() as td:
            p = Path(td) / "hourglass.env"
            p.write_text("SUPABASE_URL=https://example.test\nFOO=bar\n", encoding="utf-8")
            with patch.dict(os.environ, {"FOO": "existing"}, clear=False):
                n = load_env_file(p)
                self.assertEqual(os.environ["FOO"], "existing")
                self.assertEqual(os.environ["SUPABASE_URL"], "https://example.test")
                self.assertEqual(n, 1)


class TestEnvStatus(unittest.TestCase):
    def test_missing_keys(self):
        with patch.dict(os.environ, {}, clear=True):
            st = env_status()
            self.assertFalse(st["supabase_configured"])
            self.assertEqual(st["lgroup"], 43741)


class TestPageSmoke(unittest.TestCase):
    def test_page_renders_pt_br(self):
        st = env_status()
        body = _page(st, message="ok")
        self.assertIn("Rodízio Hourglass".encode("utf-8"), body)
        self.assertIn(b"pt-BR", body)
        self.assertIn(b"import-json", body)

    def test_apply_rows_highlighted_in_markup(self):
        st = env_status()
        doc = {
            "week": "2026-11-02",
            "suggestions": [{"role_category": "apply1", "display_name": "Maria", "status": "draft"}],
        }
        body = _page(st, suggestions=doc)
        self.assertIn(b"apply-sister", body)
        self.assertIn(b"Maria", body)

    def test_panel_public_status_shape(self):
        st = panel_public_status()
        self.assertIn("ok", st)
        self.assertIn("supabase_configured", st)


class TestImportJsonHandler(unittest.TestCase):
    def test_import_json_smoke(self):
        fake_result = {"status": "ok", "stats": {"members": 1}}
        payload = {
            "meta": {"lgroup": 43741},
            "schedules": {},
            "privileges": {},
        }

        def serve():
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), PanelHandler)
            httpd.timeout = 2
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            port = httpd.server_address[1]
            with patch(
                "colih_hourglass.web_panel._try_settings",
                return_value=(object(), None),
            ), patch(
                "colih_hourglass.web_panel.import_rotation_file",
                return_value=fake_result,
            ):
                conn = HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request(
                    "POST",
                    "/import-json",
                    body=json.dumps(payload),
                    headers={"Content-Type": "application/json"},
                )
                resp = conn.getresponse()
                body = json.loads(resp.read().decode())
                conn.close()
            httpd.shutdown()
            self.assertEqual(resp.status, 200)
            self.assertTrue(body.get("ok"))
            self.assertEqual(body.get("message"), "Importado no Colih")


if __name__ == "__main__":
    unittest.main()
