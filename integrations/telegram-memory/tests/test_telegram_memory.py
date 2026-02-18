#!/usr/bin/env python3
"""Telegram Memory Plugin — Unit Tests

All Telethon calls are mocked. No real Telegram connections needed.
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Add plugin dir to path
_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PLUGIN_DIR)
sys.path.insert(0, os.path.join(_PLUGIN_DIR, "hooks"))


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


class TestPostSession(unittest.TestCase):
    """Test post_session() with mocked Telethon."""

    @patch("telegram_memory._load_config")
    @patch("telegram_memory._get_client")
    def test_returns_message_id(self, mock_client_fn, mock_config):
        mock_config.return_value = {"api_id": 123, "api_hash": "abc", "phone": "+1", "session_path": "/tmp/test"}

        mock_msg = MagicMock()
        mock_msg.id = 42

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.send_message.return_value = mock_msg
        mock_client_fn.return_value = mock_client

        from telegram_memory import post_session
        result = post_session("Test message")
        self.assertEqual(result, 42)
        mock_client.send_message.assert_called_once()

    def test_empty_text_raises(self):
        from telegram_memory import post_session, TelegramError
        with self.assertRaises(TelegramError):
            post_session("")

    def test_none_text_raises(self):
        from telegram_memory import post_session, TelegramError
        with self.assertRaises(TelegramError):
            post_session(None)


class TestSearchFts(unittest.TestCase):
    """Test FTS5 search functionality."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "index.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _create_test_db(self, entries):
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS tg_fts USING fts5(text, date, msg_id UNINDEXED)")
        conn.execute("CREATE TABLE IF NOT EXISTS tg_meta (msg_id INTEGER PRIMARY KEY, date TEXT, synced_at REAL)")
        for text, date, msg_id in entries:
            conn.execute("INSERT INTO tg_fts (text, date, msg_id) VALUES (?, ?, ?)", (text, date, msg_id))
            conn.execute("INSERT INTO tg_meta (msg_id, date, synced_at) VALUES (?, ?, ?)", (msg_id, date, 0))
        conn.commit()
        conn.close()

    def test_empty_db_returns_empty(self):
        from on_session_start import _search_fts
        # Point to nonexistent DB
        result = _search_fts("anything")
        self.assertEqual(result, [])

    def test_populated_db_returns_matches(self):
        self._create_test_db([
            ("Gate 3 fixed test framework detection", "2026-02-18", 1),
            ("Session 125 handoff summary", "2026-02-17", 2),
            ("Telegram plugin architecture decided", "2026-02-18", 3),
        ])

        # Temporarily patch INDEX_DB
        import on_session_start
        original = on_session_start.INDEX_DB
        on_session_start.INDEX_DB = self.db_path
        try:
            result = on_session_start._search_fts("gate framework")
            self.assertGreater(len(result), 0)
            self.assertIn("source", result[0])
            self.assertEqual(result[0]["source"], "telegram_fts")
        finally:
            on_session_start.INDEX_DB = original


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


class TestOnSessionStartCli(unittest.TestCase):
    """Test on_session_start.py CLI."""

    def test_no_args_returns_empty(self):
        result = subprocess.run(
            [sys.executable, os.path.join(_PLUGIN_DIR, "hooks", "on_session_start.py")],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["count"], 0)

    def test_query_returns_valid_json(self):
        result = subprocess.run(
            [sys.executable, os.path.join(_PLUGIN_DIR, "hooks", "on_session_start.py"), "test query"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertIn("results", data)
        self.assertIn("count", data)


class TestConfigValidation(unittest.TestCase):
    """Test config.json loading and validation."""

    def test_empty_api_id_raises(self):
        from telegram_memory import TelegramError, _load_config
        # Default config has api_id=0, should raise
        with self.assertRaises(TelegramError):
            _load_config()

    def test_missing_config_raises(self):
        from telegram_memory import TelegramError
        import telegram_memory
        original = telegram_memory._CONFIG_PATH
        telegram_memory._CONFIG_PATH = "/nonexistent/config.json"
        try:
            with self.assertRaises(TelegramError):
                telegram_memory._load_config()
        finally:
            telegram_memory._CONFIG_PATH = original


if __name__ == "__main__":
    unittest.main()
