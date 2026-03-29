#!/usr/bin/env python3
"""Tests for shared/skill_llm_backend.py — claude -p LLM wrapper."""

import os
import sys
import subprocess
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.skill_llm_backend import ClaudePClient

passed = failed = 0


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} -- {detail}")


# ── Construction ──
print("\n--- skill_llm_backend: Construction ---")

client = ClaudePClient()
test("Default model is sonnet", "sonnet" in client.model)

client2 = ClaudePClient(model="claude-haiku-4-5-20251001")
test("Custom model accepted", client2.model == "claude-haiku-4-5-20251001")


# ── Successful completion ──
print("\n--- skill_llm_backend: Successful completion ---")

mock_result = MagicMock()
mock_result.returncode = 0
mock_result.stdout = '{"task_completed": true, "execution_note": "All good"}'
mock_result.stderr = ""

with patch("subprocess.run", return_value=mock_result) as mock_run:
    client = ClaudePClient()
    output = client.complete("Analyze this task")
    test("Returns stdout", output == mock_result.stdout)

    # Verify subprocess call
    call_args = mock_run.call_args
    cmd = call_args[0][0]
    test("Calls claude", cmd[0] == "claude")
    test("Uses -p flag", "-p" in cmd)
    test("Passes model", client.model in cmd)

    # Verify prompt passed via input
    test("Prompt passed as input", call_args[1]["input"] == "Analyze this task")
    test("Captures output", call_args[1]["capture_output"] is True)
    test("Text mode", call_args[1]["text"] is True)


# ── Error handling ──
print("\n--- skill_llm_backend: Error handling ---")

mock_error = MagicMock()
mock_error.returncode = 1
mock_error.stdout = ""
mock_error.stderr = "API error: rate limited"

with patch("subprocess.run", return_value=mock_error):
    client = ClaudePClient()
    try:
        client.complete("test prompt")
        test("Raises on error", False, "should have raised RuntimeError")
    except RuntimeError as e:
        test("Raises RuntimeError", True)
        test("Error contains stderr", "rate limited" in str(e))


# ── Timeout ──
print("\n--- skill_llm_backend: Timeout ---")

with patch(
    "subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=300)
):
    client = ClaudePClient()
    try:
        client.complete("long prompt")
        test("Raises on timeout", False, "should have raised")
    except subprocess.TimeoutExpired:
        test("TimeoutExpired propagated", True)


# ── Custom timeout ──
print("\n--- skill_llm_backend: Custom timeout ---")

mock_ok = MagicMock()
mock_ok.returncode = 0
mock_ok.stdout = "ok"
mock_ok.stderr = ""

with patch("subprocess.run", return_value=mock_ok) as mock_run:
    client = ClaudePClient(timeout=60)
    client.complete("quick")
    call_args = mock_run.call_args
    test("Custom timeout passed", call_args[1]["timeout"] == 60)


# ── Max tokens flag ──
print("\n--- skill_llm_backend: Max tokens ---")

with patch("subprocess.run", return_value=mock_ok) as mock_run:
    client = ClaudePClient()
    client.complete("prompt", max_tokens=2000)
    cmd = mock_run.call_args[0][0]
    test("Max tokens in cmd", "--max-tokens" in cmd, f"cmd: {cmd}")
    if "--max-tokens" in cmd:
        idx = cmd.index("--max-tokens")
        test("Max tokens value", cmd[idx + 1] == "2000")


print(f"\n{'=' * 40}")
print(f"skill_llm_backend: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
