import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from colih_hourglass.env_loader import load_env_file
from colih_hourglass.web_panel import _page, env_status


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
        self.assertIn(b"Painel local", body)
        self.assertIn(b"pt-BR", body)
        self.assertIn(b"Importar export JSON", body)

    def test_apply_rows_highlighted_in_markup(self):
        st = env_status()
        doc = {
            "week": "2026-11-02",
            "suggestions": [{"role_category": "apply1", "display_name": "Maria", "status": "draft"}],
        }
        body = _page(st, suggestions=doc)
        self.assertIn(b"apply-sister", body)


if __name__ == "__main__":
    unittest.main()
