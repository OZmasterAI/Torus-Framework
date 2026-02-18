#!/usr/bin/env python3
"""Telegram Bot — Unit Tests

All Telegram and Claude calls are mocked. No real connections needed.
"""

import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Add plugin dir to path
_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PLUGIN_DIR)
sys.path.insert(0, os.path.join(_PLUGIN_DIR, "hooks"))


# --- TestFormatHtml ---

class TestFormatHtml(unittest.TestCase):
    """Test HANDOFF.md -> Telegram HTML conversion."""

    def setUp(self):
        from on_session_end import _format_html
        self.format_html = _format_html

    def test_heading_conversion(self):
        md = "# Session 127\n## What Was Done\n- Item 1"
        html = self.format_html(md, "127")
        self.assertIn("<b>Session 127</b>", html)
        self.assertIn("<b>What Was Done</b>", html)

    def test_bold_conversion(self):
        md = "- **Gate 3**: Fixed detection"
        html = self.format_html(md, "1")
        self.assertIn("<b>Gate 3</b>", html)

    def test_hashtag_presence(self):
        md = "# Test\nSome content"
        html = self.format_html(md, "42")
        self.assertIn("#torus", html)
        self.assertIn("#session", html)
        self.assertIn("#session42", html)

    def test_length_cap(self):
        md = "# Big Session\n" + "x" * 5000
        html = self.format_html(md, "1")
        self.assertLessEqual(len(html), 4096)

    def test_empty_input(self):
        html = self.format_html("", "1")
        self.assertIn("#torus", html)

    def test_code_conversion(self):
        md = "Run `pytest` to test"
        html = self.format_html(md, "1")
        self.assertIn("<code>pytest</code>", html)


# --- TestDbLayer ---

class TestDbLayer(unittest.TestCase):
    """Test FTS5 database operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_init_creates_tables(self):
        from db import init_db
        init_db(self.db_path)
        conn = sqlite3.connect(self.db_path)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual table')").fetchall()]
        conn.close()
        self.assertIn("tg_fts", tables)
        self.assertIn("tg_meta", tables)

    def test_log_and_search(self):
        from db import init_db, log_message, search_fts
        init_db(self.db_path)
        log_message(self.db_path, 123, "user", "hello world test message", "2026-02-18")
        results = search_fts(self.db_path, "hello", limit=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["sender"], "user")
        self.assertEqual(int(results[0]["chat_id"]), 123)
        self.assertEqual(results[0]["source"], "bot_fts")

    def test_get_recent(self):
        from db import init_db, log_message, get_recent
        init_db(self.db_path)
        log_message(self.db_path, 123, "user", "first message", "2026-02-18T10:00:00")
        log_message(self.db_path, 123, "Claude", "response here", "2026-02-18T10:00:01")
        log_message(self.db_path, 456, "other", "different chat", "2026-02-18T10:00:02")
        recent = get_recent(self.db_path, 123, limit=10)
        self.assertEqual(len(recent), 2)

    def test_empty_text_skipped(self):
        from db import init_db, log_message
        init_db(self.db_path)
        result = log_message(self.db_path, 123, "user", "", "2026-02-18")
        self.assertIsNone(result)

    def test_search_nonexistent_db(self):
        from db import search_fts
        results = search_fts("/nonexistent/db.sqlite", "hello")
        self.assertEqual(results, [])


# --- TestSessionPersistence ---

class TestSessionPersistence(unittest.TestCase):
    """Test session ID persistence."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sessions_path = os.path.join(self.tmpdir, "sessions.json")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_and_load(self):
        from sessions import save_session, get_session_id
        save_session(self.sessions_path, 123, "sess-abc-123")
        result = get_session_id(self.sessions_path, 123)
        self.assertEqual(result, "sess-abc-123")

    def test_missing_chat_returns_none(self):
        from sessions import save_session, get_session_id
        save_session(self.sessions_path, 123, "sess-abc")
        result = get_session_id(self.sessions_path, 999)
        self.assertIsNone(result)

    def test_load_nonexistent_returns_empty(self):
        from sessions import load_sessions
        result = load_sessions("/nonexistent/sessions.json")
        self.assertEqual(result, {})


# --- TestClaudeRunner ---

class TestClaudeRunner(unittest.TestCase):
    """Test Claude subprocess wrapper (all mocked)."""

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    @patch("claude_runner.asyncio.create_subprocess_exec")
    def test_successful_run(self, mock_exec):
        from claude_runner import run_claude
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (
            json.dumps({"result": "Hello!", "session_id": "sess-123"}).encode(),
            b"",
        )
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        result, sid = self._run(run_claude("test message"))
        self.assertEqual(result, "Hello!")
        self.assertEqual(sid, "sess-123")

    @patch("claude_runner.asyncio.create_subprocess_exec")
    def test_nonzero_exit(self, mock_exec):
        from claude_runner import run_claude, ClaudeError
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"some error")
        mock_proc.returncode = 1
        mock_exec.return_value = mock_proc

        with self.assertRaises(ClaudeError):
            self._run(run_claude("test"))

    @patch("claude_runner.asyncio.create_subprocess_exec")
    def test_invalid_json(self, mock_exec):
        from claude_runner import run_claude, ClaudeError
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"not json", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        with self.assertRaises(ClaudeError):
            self._run(run_claude("test"))

    @patch("claude_runner.asyncio.create_subprocess_exec")
    def test_with_session_resume(self, mock_exec):
        from claude_runner import run_claude
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (
            json.dumps({"result": "Resumed!", "session_id": "sess-456"}).encode(),
            b"",
        )
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        result, sid = self._run(run_claude("test", session_id="sess-old"))
        self.assertEqual(result, "Resumed!")
        self.assertEqual(sid, "sess-456")
        # Verify --resume was in the command
        call_args = mock_exec.call_args[0]
        self.assertIn("--resume", call_args)
        self.assertIn("sess-old", call_args)


# --- TestConfigLoading ---

class TestConfigLoading(unittest.TestCase):
    """Test config.json loading and validation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_missing_file_raises(self):
        from config import load_config, BotConfigError
        with self.assertRaises(BotConfigError):
            load_config("/nonexistent/config.json")

    def test_missing_token_raises(self):
        from config import load_config, BotConfigError
        path = os.path.join(self.tmpdir, "cfg.json")
        with open(path, "w") as f:
            json.dump({"bot_token": "", "allowed_users": []}, f)
        with self.assertRaises(BotConfigError):
            load_config(path)

    def test_valid_config(self):
        from config import load_config
        path = os.path.join(self.tmpdir, "cfg.json")
        with open(path, "w") as f:
            json.dump({"bot_token": "test:token", "allowed_users": [123]}, f)
        cfg = load_config(path)
        self.assertEqual(cfg["bot_token"], "test:token")
        self.assertEqual(cfg["allowed_users"], [123])
        self.assertIn("claude_cwd", cfg)  # default filled


# --- TestSearchCli ---

class TestSearchCli(unittest.TestCase):
    """Test search.py CLI JSON output."""

    def test_json_output_format(self):
        result = subprocess.run(
            [sys.executable, os.path.join(_PLUGIN_DIR, "search.py"), "test", "--json"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertIn("results", data)
        self.assertIn("count", data)
        self.assertIsInstance(data["results"], list)

    def test_empty_query(self):
        result = subprocess.run(
            [sys.executable, os.path.join(_PLUGIN_DIR, "search.py"), "", "--json"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["count"], 0)

    def test_limit_flag(self):
        result = subprocess.run(
            [sys.executable, os.path.join(_PLUGIN_DIR, "search.py"), "test", "--json", "--limit", "3"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertIn("results", data)


if __name__ == "__main__":
    unittest.main()
