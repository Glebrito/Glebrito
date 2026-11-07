import io
import sys
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from colih_hourglass.cli import cmd_atualizar
from colih_hourglass.hourglass_api import session_setup_help_pt


class TestAtualizarSession(unittest.TestCase):
    def test_missing_session_prints_help_and_exits(self) -> None:
        args = Namespace(
            env_file=None,
            date_from="2025-04-01",
            date_to="2026-12-31",
            week=None,
            suggest=False,
            persist=False,
            json_out=None,
        )
        buf = io.StringIO()
        with patch("colih_hourglass.cli.resolve_session_path", return_value=None), patch.dict(
            "os.environ",
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": "test-key",
            },
            clear=False,
        ), redirect_stderr(buf), self.assertRaises(SystemExit) as ctx:
            cmd_atualizar(args)
        self.assertEqual(ctx.exception.code, 2)
        err = buf.getvalue()
        self.assertIn("hourglass.curl.txt", err)
        self.assertIn(".hourglass-session.json", err)

    def test_session_help_is_three_lines(self) -> None:
        lines = [ln for ln in session_setup_help_pt().strip().split("\n") if ln.strip()]
        self.assertEqual(len(lines), 3)

    def test_401_prints_help(self) -> None:
        args = Namespace(
            env_file=None,
            date_from="2025-04-01",
            date_to="2026-12-31",
            week=None,
            suggest=False,
            persist=False,
            json_out=None,
        )
        from pathlib import Path

        buf = io.StringIO()
        with patch("colih_hourglass.cli.resolve_session_path", return_value=Path("/tmp/x.json")), patch(
            "colih_hourglass.cli.load_session",
            return_value={"cookie": "c", "xsrf": "t", "base": "https://app.hourglass-app.com"},
        ), patch(
            "colih_hourglass.cli.sync_from_hourglass",
            side_effect=RuntimeError("Hourglass HTTP 401 — sessão expirada ou inválida."),
        ), patch.dict(
            "os.environ",
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": "test-key",
            },
            clear=False,
        ), redirect_stderr(buf), self.assertRaises(SystemExit) as ctx:
            cmd_atualizar(args)
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("session save", buf.getvalue())


class TestAtualizarSuggestMarkdown(unittest.TestCase):
    def test_week_triggers_markdown(self) -> None:
        args = Namespace(
            env_file=None,
            date_from="2025-04-01",
            date_to="2026-12-31",
            week="2026-11-09",
            suggest=False,
            persist=False,
            json_out=None,
        )
        fake_sync = {"status": "ok", "stats": {"members": 2}}
        fake_suggest = {
            "week": "2026-11-09",
            "suggestions": [
                {"role_category": "chairman", "display_name": "João Silva", "status": "draft"},
            ],
        }
        out = io.StringIO()
        from pathlib import Path

        with patch("colih_hourglass.cli.resolve_session_path", return_value=Path("/tmp/x.json")), patch(
            "colih_hourglass.cli.load_session",
            return_value={"cookie": "c", "xsrf": "t", "base": "https://app.hourglass-app.com"},
        ), patch("colih_hourglass.cli.sync_from_hourglass", return_value=fake_sync), patch(
            "colih_hourglass.cli.run_suggest_week",
            return_value=fake_suggest,
        ), patch.dict(
            "os.environ",
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": "test-key",
            },
            clear=False,
        ), redirect_stdout(out):
            cmd_atualizar(args)
        text = out.getvalue()
        self.assertIn("João Silva", text)
        self.assertIn("| Presidente |", text)
        self.assertNotIn("id:", text)


if __name__ == "__main__":
    unittest.main()
