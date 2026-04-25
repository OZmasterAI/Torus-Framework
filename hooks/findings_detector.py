#!/usr/bin/env python3
"""PostToolUse hook — auto-detects security findings and bugs in tool output.

Fires on Bash output. Pattern-matches for CVEs, vulnerability keywords,
panics, segfaults, and other significant findings. Saves to the
security-findings repo as auto-detected entries for later review.

Exit 0 always (non-blocking, fail-open).
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime

REPO = os.path.expanduser("~/projects/security-findings")
DEDUP_FILE = os.path.join(REPO, ".detected_hashes")
MATCH_TOOLS = {"Bash", "mcp__toolshed__run_tool"}

SECURITY_PATTERNS = [
    (r"CVE-\d{4}-\d{4,}", "cve", "security", "high"),
    (r"GHSA-[\w-]+", "ghsa", "security", "high"),
    (r"command\s+injection", "command-injection", "security", "high"),
    (r"SQL\s+injection", "sql-injection", "security", "high"),
    (r"XSS|cross.site\s+scripting", "xss", "security", "high"),
    (r"CSRF|cross.site\s+request\s+forgery", "csrf", "security", "medium"),
    (r"path\s+traversal|directory\s+traversal", "path-traversal", "security", "high"),
    (r"authentication\s+bypass|auth\s+bypass", "auth-bypass", "security", "high"),
    (r"privilege\s+escalation", "priv-escalation", "security", "high"),
    (r"remote\s+code\s+execution|\bRCE\b", "rce", "security", "high"),
    (r"server.side\s+request\s+forgery|\bSSRF\b", "ssrf", "security", "high"),
    (r"insecure\s+direct\s+object\s+ref|\bIDOR\b", "idor", "security", "medium"),
    (
        r"buffer\s+overflow|heap\s+overflow|stack\s+overflow",
        "overflow",
        "security",
        "high",
    ),
    (r"use.after.free|double\s+free", "memory-safety", "security", "high"),
    (
        r"hardcoded\s+(password|secret|key|credential)",
        "hardcoded-secret",
        "security",
        "high",
    ),
    (
        r"\d+\s+(high|critical)\s+severity\s+vulnerabilit",
        "audit-finding",
        "security",
        "medium",
    ),
    # Web/API
    (r"open\s+redirect", "open-redirect", "security", "medium"),
    (r"prototype\s+pollution", "prototype-pollution", "security", "high"),
    (r"XXE|xml\s+external\s+entity", "xxe", "security", "high"),
    (r"server.side\s+template\s+injection|\bSSTI\b", "ssti", "security", "high"),
    (
        r"insecure\s+deserialization|unsafe\s+deserialization",
        "insecure-deser",
        "security",
        "high",
    ),
    (
        r"alg[\"']?\s*:\s*[\"']?none|algorithm\s+confusion",
        "jwt-alg-none",
        "security",
        "high",
    ),
    (
        r"CORS\s+misconfig|Access-Control-Allow-Origin:\s*\*",
        "cors-misconfig",
        "security",
        "medium",
    ),
    # Crypto
    (r"weak\s+(cipher|hash|encryption)", "weak-crypto", "security", "medium"),
    (
        r"\bMD5\b.*(?:password|auth|sign|verif|token)",
        "md5-security",
        "security",
        "medium",
    ),
    (
        r"\bSHA-?1\b.*(?:password|auth|sign|verif|token)",
        "sha1-security",
        "security",
        "medium",
    ),
    (r"\bECB\b\s*mode", "ecb-mode", "security", "medium"),
    (r"hardcoded\s+(IV|nonce)|nonce\s+reuse", "nonce-reuse", "security", "high"),
    # Dependency audit tools
    (r"npm\s+warn.*audit|yarn\s+audit", "npm-audit", "security", "medium"),
    (r"pip-audit.*found\s+\d+\s+vuln", "pip-audit", "security", "medium"),
    (
        r"govulncheck.*(?:GO-\d{4}-\d+|found\s+\d+\s+vuln)",
        "govulncheck",
        "security",
        "high",
    ),
    (
        r"cargo\s+audit.*(?:RUSTSEC|found\s+\d+\s+vuln)",
        "cargo-audit",
        "security",
        "medium",
    ),
    (r"bandit.*(?:Issue|severity:\s*(?:HIGH|MEDIUM))", "bandit", "security", "medium"),
    (r"semgrep.*(?:error|warning).*(?:security|vuln)", "semgrep", "security", "medium"),
    (r"gosec.*(?:G\d{3}|found\s+\d+\s+issue)", "gosec", "security", "medium"),
]

BUG_PATTERNS = [
    (r"panic:\s+", "panic", "bugs", "high"),
    (r"SIGSEGV|segmentation\s+fault", "segfault", "bugs", "high"),
    (r"nil\s+pointer\s+dereference|null\s*pointer", "null-deref", "bugs", "high"),
    (r"data\s+race\s+detected", "data-race", "bugs", "high"),
    (r"deadlock\s+detected", "deadlock", "bugs", "high"),
    (r"fatal\s+error:\s+concurrent\s+map", "concurrent-map", "bugs", "high"),
    (r"out\s+of\s+memory|OOM\s+killed", "oom", "errors", "high"),
    # Python
    (r"Traceback \(most recent call last\)", "python-traceback", "bugs", "medium"),
    # Node.js
    (r"UnhandledPromiseRejection", "unhandled-promise", "bugs", "medium"),
    (r"MaxListenersExceededWarning", "listener-leak", "bugs", "medium"),
    # Go
    (r"WARNING:\s*DATA\s*RACE", "go-race", "bugs", "high"),
    (
        r"fatal\s+error:\s+all\s+goroutines\s+are\s+asleep",
        "goroutine-deadlock",
        "bugs",
        "high",
    ),
    (r"goroutine\s+leak", "goroutine-leak", "bugs", "medium"),
    # General
    (r"integer\s+overflow|integer\s+underflow", "integer-overflow", "bugs", "high"),
    (r"division\s+by\s+zero|divide\s+by\s+zero", "div-by-zero", "bugs", "high"),
    (r"SIGABRT|abort\s+trap", "sigabrt", "bugs", "high"),
    (r"core\s+dumped", "core-dump", "bugs", "high"),
    (r"assertion\s+failed|assert.*failed", "assertion-failure", "bugs", "medium"),
]

ALL_PATTERNS = [
    (re.compile(p, re.IGNORECASE), name, cat, sev)
    for p, name, cat, sev in SECURITY_PATTERNS + BUG_PATTERNS
]

CATEGORY_DIRS = {
    "security": "detected/security",
    "bugs": "detected/bugs",
    "errors": "detected/errors",
}


def _fnv1a(s: str) -> str:
    h = 0xCBF29CE484222325
    for b in s.encode():
        h ^= b
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return format(h, "016x")


def _already_detected(hash_val: str) -> bool:
    if not os.path.exists(DEDUP_FILE):
        return False
    with open(DEDUP_FILE) as f:
        return hash_val in f.read()


def _record_hash(hash_val: str) -> None:
    with open(DEDUP_FILE, "a") as f:
        f.write(hash_val + "\n")


def _extract_context(output: str, match_start: int, window: int = 300) -> str:
    start = max(0, match_start - window)
    end = min(len(output), match_start + window)
    snippet = output[start:end].strip()
    if len(snippet) > 580:
        snippet = snippet[:580] + "..."
    return snippet


def save_detected(
    title,
    category,
    project,
    source_tool,
    confidence,
    pattern_name,
    severity,
    summary,
    source_output,
    working_dir,
    session_id,
):
    date = datetime.now().strftime("%Y-%m-%d")
    slug = re.sub(r"[^\w-]", "-", title.lower().strip())[:60].rstrip("-")
    subdir = CATEGORY_DIRS.get(category, "detected/security")
    filename = f"{date}-{slug}.md"
    filepath = os.path.join(REPO, subdir, filename)

    if os.path.exists(filepath):
        return

    template_path = os.path.join(REPO, "templates", "detected.md")
    with open(template_path) as f:
        content = f.read()

    content = content.format(
        title=title,
        category=category,
        project=project,
        date=date,
        source_tool=source_tool,
        confidence=confidence,
        pattern_matched=pattern_name,
        summary=f"[{severity.upper()}] {summary}",
        source_output=source_output.replace("`", "'"),
        working_directory=working_dir,
        session_id=session_id,
    )

    with open(filepath, "w") as f:
        f.write(content)

    subprocess.run(["git", "add", filepath], cwd=REPO, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", f"detected({category}): {title}"],
        cwd=REPO,
        capture_output=True,
    )


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    if tool_name not in MATCH_TOOLS:
        sys.exit(0)

    raw_response = data.get("tool_response", "")
    if not raw_response:
        sys.exit(0)
    if isinstance(raw_response, dict):
        response = (
            raw_response.get("content", "")
            or raw_response.get("output", "")
            or raw_response.get("stdout", "")
            or str(raw_response)
        )
    else:
        response = str(raw_response)

    # Quick pre-filter: skip short outputs unlikely to contain findings
    if len(response) < 30:
        sys.exit(0)

    # Self-reference filter: ignore commands operating on the findings repo itself
    command = (
        data.get("tool_input", {}).get("command", "") if tool_name == "Bash" else ""
    )
    if "security-findings" in command:
        sys.exit(0)

    session_id = data.get("session_id", "unknown")
    working_dir = command[:100] if tool_name == "Bash" else ""
    project = os.path.basename(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))

    for pattern, name, category, severity in ALL_PATTERNS:
        match = pattern.search(response)
        if match:
            content_hash = _fnv1a(f"{name}:{match.group()}")
            if _already_detected(content_hash):
                continue

            context = _extract_context(response, match.start())
            title = f"{name}-{match.group()[:40]}"
            title = re.sub(r"[^\w\s.-]", "", title).strip()

            save_detected(
                title=title,
                category=category,
                project=project,
                source_tool=tool_name,
                confidence="medium",
                pattern_name=name,
                severity=severity,
                summary=f"Auto-detected {name} pattern: {match.group()[:100]}",
                source_output=context,
                working_dir=working_dir,
                session_id=session_id,
            )
            _record_hash(content_hash)

    sys.exit(0)


if __name__ == "__main__":
    main()
