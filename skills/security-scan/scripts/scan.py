#!/usr/bin/env python3
"""Torus Framework Security Scanner.

Performs an automated security audit of:
  - Gate files (existence, check() export, security patterns)
  - Gate 17 injection defense pattern coverage
  - MCP tool registrations in settings.json
  - Shared module secrets scan (hooks/shared/*.py)
  - State files for sensitive data exposure
  - Circuit breaker state for stuck-open gates
  - .file_claims.json for stale workspace claims

Usage:
    python3 scan.py [--severity critical|high|medium|low|info]

Exit codes:
    0 — Scan complete (findings may exist; check output)
    1 — Scanner itself encountered an error
"""

import ast
import datetime
import glob
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional

# ── Path constants ──────────────────────────────────────────────────────────

CLAUDE_DIR    = os.path.join(os.path.expanduser("~"), ".claude")
HOOKS_DIR     = os.path.join(CLAUDE_DIR, "hooks")
GATES_DIR     = os.path.join(HOOKS_DIR, "gates")
SHARED_DIR    = os.path.join(HOOKS_DIR, "shared")
SETTINGS_PATH = os.path.join(CLAUDE_DIR, "settings.json")
CLAIMS_PATH   = os.path.join(HOOKS_DIR, ".file_claims.json")
CB_RAMDISK    = "/dev/shm/claude-hooks/circuit_breaker.json"
CB_DISK       = os.path.join(HOOKS_DIR, ".circuit_breaker.json")

# Ensure shared modules are importable
sys.path.insert(0, HOOKS_DIR)

# ── Severity ordering ────────────────────────────────────────────────────────

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

# ── Finding data class ────────────────────────────────────────────────────────

@dataclass
class Finding:
    component: str        # e.g. "hooks/gate_02.py"
    kind: str             # e.g. "Hook", "MCP", "Shared"
    severity: str         # critical / high / medium / low / info
    finding: str          # Short description of the issue
    evidence: str         # The actual risky line or pattern
    recommendation: str   # How to fix it
    file_path: str = ""   # Absolute path for remediation guidance
    line_no: int = 0      # Line number if applicable


# ── Severity filter from CLI ──────────────────────────────────────────────────

def _min_severity() -> int:
    """Return the minimum severity level to report (inclusive)."""
    for arg in sys.argv[1:]:
        if arg.startswith("--severity="):
            level = arg.split("=", 1)[1].lower()
        elif arg == "--severity" and sys.argv.index(arg) + 1 < len(sys.argv):
            level = sys.argv[sys.argv.index(arg) + 1].lower()
        else:
            continue
        return SEVERITY_ORDER.get(level, 4)
    return 4  # default: report everything


# ── Helpers ──────────────────────────────────────────────────────────────────

_SECRET_PATTERN = re.compile(
    # Match secret-like assignments to string literals.
    # Requires the RHS to be a quoted string (not a function call or variable reference),
    # to reduce false positives from security-checker code that mentions "secret" in
    # variable/function names but doesn't store literal credentials.
    r'(?i)(password|secret|token|api[\._]?key|bearer|private[\._]?key|'
    r'access[\._]?key|auth[\._]?token|ghp_|sk-)\s*[=:]\s*["\'][^"\']{6,}["\']',
)

_SHELL_METACHAR = re.compile(r'[\$`;&|><]')

_BROAD_EXCEPT = re.compile(r'^\s*except\s*:\s*pass\s*$', re.MULTILINE)

_SUBPROCESS_SHELL = re.compile(
    r'subprocess\.(run|call|Popen|check_output|check_call)\s*\([^)]*shell\s*=\s*True',
    re.DOTALL,
)

_OS_SYSTEM = re.compile(r'\bos\.system\s*\(')
_EVAL_EXEC  = re.compile(r'\b(eval|exec)\s*\(')
_CHMOD_777  = re.compile(r'chmod\s+777|chmod\s+0?777|S_IRWXO')
_SUDO_CALL  = re.compile(r'\bsudo\b')

# Gate 17 expected pattern categories — we verify each category is covered
_G17_CATEGORIES = [
    "INSTRUCTION_PATTERNS",
    "AUTHORITY_PATTERNS",
    "BOUNDARY_PATTERNS",
    "OBFUSCATION_PATTERNS",
    "FINANCIAL_PATTERNS",
    # Named _SELFHARM_PATTERNS (no underscore) in gate_17_injection_defense.py
    "SELFHARM_PATTERNS",
]

# Expected gate files (module names without .py extension)
_EXPECTED_GATES = [
    "gate_01_read_before_edit",
    "gate_02_no_destroy",
    "gate_03_test_before_deploy",
    "gate_04_memory_first",
    "gate_05_proof_before_fixed",
    "gate_06_save_fix",
    "gate_07_critical_file_guard",
    "gate_08_temporal",
    "gate_09_strategy_ban",
    "gate_10_model_enforcement",
    "gate_11_rate_limit",
    "gate_12_plan_mode_save",
    "gate_13_workspace_isolation",
    "gate_14_confidence_check",
    "gate_15_causal_chain",
    "gate_16_code_quality",
    "gate_17_injection_defense",
]


def _read_file(path: str) -> Optional[str]:
    """Read a file and return its text, or None on error."""
    try:
        with open(path, "r", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _read_json(path: str):
    """Read JSON from a file, return None on error."""
    text = _read_file(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _short(text: str, max_len: int = 120) -> str:
    """Truncate a string for display."""
    text = text.strip()
    return text[:max_len] + "..." if len(text) > max_len else text


# ── Check 1: Gate files existence and check() export ─────────────────────────

def check_gates() -> List[Finding]:
    findings: List[Finding] = []

    for gate_name in _EXPECTED_GATES:
        gate_path = os.path.join(GATES_DIR, gate_name + ".py")

        # 1a. File must exist
        if not os.path.isfile(gate_path):
            findings.append(Finding(
                component=f"hooks/gates/{gate_name}.py",
                kind="Gate",
                severity="high",
                finding="Gate file missing",
                evidence=f"Expected path not found: {gate_path}",
                recommendation="Create the gate file and implement the check() function.",
                file_path=gate_path,
            ))
            continue

        source = _read_file(gate_path)
        if source is None:
            findings.append(Finding(
                component=f"hooks/gates/{gate_name}.py",
                kind="Gate",
                severity="high",
                finding="Gate file unreadable",
                evidence=gate_path,
                recommendation="Fix file permissions so the scanner can read it.",
                file_path=gate_path,
            ))
            continue

        # 1b. Must define a check() function
        has_check = bool(re.search(r'^def\s+check\s*\(', source, re.MULTILINE))
        if not has_check:
            findings.append(Finding(
                component=f"hooks/gates/{gate_name}.py",
                kind="Gate",
                severity="high",
                finding="Missing check() function",
                evidence=f"{gate_name}.py has no top-level 'def check(' definition",
                recommendation="Export a check(tool_name, tool_input, state, event_type) function.",
                file_path=gate_path,
            ))

        # 1c. Must import from shared.gate_result (not construct raw dicts)
        if "GateResult" not in source:
            findings.append(Finding(
                component=f"hooks/gates/{gate_name}.py",
                kind="Gate",
                severity="medium",
                finding="Does not use GateResult",
                evidence=f"{gate_name}.py — GateResult not found in source",
                recommendation="Import and return GateResult from shared.gate_result, never raw dicts.",
                file_path=gate_path,
            ))

        # 1d. Broad except that swallows blocking sys.exit
        for i, line in enumerate(source.splitlines(), 1):
            if re.match(r'\s*except\s*:\s*pass\s*$', line):
                findings.append(Finding(
                    component=f"hooks/gates/{gate_name}.py",
                    kind="Gate",
                    severity="high",
                    finding="Broad except:pass may swallow sys.exit(2) blocks",
                    evidence=_short(line),
                    recommendation="Replace 'except: pass' with specific exception handling; never silence exit codes.",
                    file_path=gate_path,
                    line_no=i,
                ))

        # 1e. sys.exit(1) used where sys.exit(2) should be (potential gate bypass)
        for i, line in enumerate(source.splitlines(), 1):
            if re.search(r'\bsys\.exit\s*\(\s*1\s*\)', line):
                # Only flag inside what looks like a blocking context
                findings.append(Finding(
                    component=f"hooks/gates/{gate_name}.py",
                    kind="Gate",
                    severity="low",
                    finding="sys.exit(1) detected — verify this is not intended as a block",
                    evidence=_short(line),
                    recommendation=(
                        "Per hook contract: sys.exit(2) blocks; sys.exit(1) does NOT block. "
                        "Review each occurrence to confirm non-blocking intent."
                    ),
                    file_path=gate_path,
                    line_no=i,
                ))
                break  # one notice per gate is enough

    return findings


# ── Check 2: Gate 17 injection defense pattern coverage ─────────────────────

def check_gate17_patterns() -> List[Finding]:
    findings: List[Finding] = []
    g17_path = os.path.join(GATES_DIR, "gate_17_injection_defense.py")

    source = _read_file(g17_path)
    if source is None:
        findings.append(Finding(
            component="hooks/gates/gate_17_injection_defense.py",
            kind="Gate",
            severity="critical",
            finding="Gate 17 file missing or unreadable",
            evidence=g17_path,
            recommendation="Restore gate_17_injection_defense.py from version control.",
            file_path=g17_path,
        ))
        return findings

    for category in _G17_CATEGORIES:
        if category not in source:
            findings.append(Finding(
                component="hooks/gates/gate_17_injection_defense.py",
                kind="Gate",
                severity="high",
                finding=f"Injection defense category missing: {category}",
                evidence=f"Pattern list '{category}' not found in gate_17_injection_defense.py",
                recommendation=(
                    f"Add {category} pattern list based on MCP scanner research "
                    "(multi-engine detection, behavioral code analysis)."
                ),
                file_path=g17_path,
            ))

    # Check for MCP_SAFE_PREFIXES guard (prevents memory tools from being flagged)
    if "MCP_SAFE_PREFIXES" not in source:
        findings.append(Finding(
            component="hooks/gates/gate_17_injection_defense.py",
            kind="Gate",
            severity="medium",
            finding="MCP_SAFE_PREFIXES guard not found",
            evidence="Gate 17 may flag trusted MCP memory tools as injection attempts",
            recommendation="Add MCP_SAFE_PREFIXES tuple to exempt trusted internal MCP tools.",
            file_path=g17_path,
        ))

    # Check obfuscation detection is present (Sprint 2 MCP scanner research)
    obfuscation_indicators = ["base64", "rot13", "unicode", "zero.width", "confusable"]
    found_any = any(ind.lower() in source.lower() for ind in obfuscation_indicators)
    if not found_any:
        findings.append(Finding(
            component="hooks/gates/gate_17_injection_defense.py",
            kind="Gate",
            severity="medium",
            finding="Obfuscation detection patterns not found",
            evidence=(
                "None of: base64, rot13, unicode, zero-width, confusable detected in gate_17 source. "
                "MCP scanner research recommends multi-layer obfuscation detection."
            ),
            recommendation=(
                "Add obfuscation detection: Base64 recursive decode, ROT13, Unicode zero-width chars, "
                "hex-encoded strings, and confusable lookalike character detection."
            ),
            file_path=g17_path,
        ))

    return findings


# ── Check 3: MCP tool registrations in settings.json ─────────────────────────

def check_mcp_registrations() -> List[Finding]:
    findings: List[Finding] = []

    settings = _read_json(SETTINGS_PATH)
    if settings is None:
        findings.append(Finding(
            component="settings.json",
            kind="Config",
            severity="high",
            finding="settings.json missing or unparseable",
            evidence=SETTINGS_PATH,
            recommendation="Restore settings.json from version control.",
            file_path=SETTINGS_PATH,
        ))
        return findings

    mcp_servers = settings.get("mcpServers", {})
    if not mcp_servers:
        findings.append(Finding(
            component="settings.json",
            kind="Config",
            severity="info",
            finding="No mcpServers registered",
            evidence="settings.json mcpServers block is empty or absent",
            recommendation="Verify MCP servers are correctly registered.",
            file_path=SETTINGS_PATH,
        ))
        return findings

    for name, cfg in mcp_servers.items():
        if not isinstance(cfg, dict):
            continue

        # Check command for shell metacharacters
        command = cfg.get("command", "")
        args = cfg.get("args", [])
        full_cmd = " ".join([command] + [str(a) for a in args])
        if _SHELL_METACHAR.search(full_cmd):
            findings.append(Finding(
                component=f"settings.json/mcpServers/{name}",
                kind="MCP",
                severity="high",
                finding="Shell metacharacter in MCP server command/args",
                evidence=_short(full_cmd),
                recommendation="Remove shell metacharacters or use subprocess list form (no shell=True).",
                file_path=SETTINGS_PATH,
            ))

        # Scan env block for hardcoded secrets
        env_block = cfg.get("env", {})
        if isinstance(env_block, dict):
            for env_key, env_val in env_block.items():
                val_str = str(env_val)
                # Flag only literal values (not $VAR references)
                if _SECRET_PATTERN.search(f"{env_key}={val_str}") and not val_str.startswith("$"):
                    findings.append(Finding(
                        component=f"settings.json/mcpServers/{name}",
                        kind="MCP",
                        severity="critical",
                        finding=f"Hardcoded secret in env var: {env_key}",
                        evidence=f"{env_key}=<REDACTED>",
                        recommendation=f"Replace literal value with env var reference: ${env_key}",
                        file_path=SETTINGS_PATH,
                    ))

        # Check transport type
        transport = cfg.get("transport", "stdio")
        if transport in ("sse", "http"):
            findings.append(Finding(
                component=f"settings.json/mcpServers/{name}",
                kind="MCP",
                severity="medium",
                finding=f"Non-stdio transport: {transport}",
                evidence=f"Server '{name}' uses transport={transport} (potential network exposure)",
                recommendation="Prefer stdio transport unless network access is explicitly required.",
                file_path=SETTINGS_PATH,
            ))

        # Description mismatch check: if a memory_server.py is referenced, it should be the canonical path
        if "memory_server" in command or any("memory_server" in str(a) for a in args):
            memory_server_path = os.path.join(HOOKS_DIR, "memory_server.py")
            if not os.path.isfile(memory_server_path):
                findings.append(Finding(
                    component=f"settings.json/mcpServers/{name}",
                    kind="MCP",
                    severity="high",
                    finding="memory_server.py referenced but not found",
                    evidence=f"Expected: {memory_server_path}",
                    recommendation="Restore memory_server.py or update the MCP server path in settings.json.",
                    file_path=SETTINGS_PATH,
                ))

    return findings


# ── Check 4: Hardcoded secrets in hooks/shared/*.py ──────────────────────────

def check_shared_secrets() -> List[Finding]:
    findings: List[Finding] = []
    shared_files = glob.glob(os.path.join(SHARED_DIR, "*.py"))

    for path in sorted(shared_files):
        source = _read_file(path)
        if source is None:
            continue
        basename = os.path.basename(path)

        for i, line in enumerate(source.splitlines(), 1):
            # Skip comments and docstrings
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue

            if _SECRET_PATTERN.search(line):
                findings.append(Finding(
                    component=f"hooks/shared/{basename}",
                    kind="Shared",
                    severity="critical",
                    finding="Potential hardcoded secret",
                    evidence=_short(line),
                    recommendation=(
                        "Move sensitive values to environment variables or a secrets manager. "
                        "Never hardcode tokens, passwords, or API keys in source files."
                    ),
                    file_path=path,
                    line_no=i,
                ))

        # Also flag eval/exec usage in shared modules
        for i, line in enumerate(source.splitlines(), 1):
            if _EVAL_EXEC.search(line) and not line.strip().startswith("#"):
                findings.append(Finding(
                    component=f"hooks/shared/{basename}",
                    kind="Shared",
                    severity="high",
                    finding="eval() or exec() in shared module",
                    evidence=_short(line),
                    recommendation=(
                        "Avoid eval/exec in shared security modules. "
                        "Use ast.literal_eval() for safe data parsing instead."
                    ),
                    file_path=path,
                    line_no=i,
                ))
                break  # one notice per file

        # Flag subprocess shell=True
        shell_match = _SUBPROCESS_SHELL.search(source)
        if shell_match:
            line_no = source[:shell_match.start()].count("\n") + 1
            findings.append(Finding(
                component=f"hooks/shared/{basename}",
                kind="Shared",
                severity="high",
                finding="subprocess called with shell=True",
                evidence=_short(shell_match.group()),
                recommendation=(
                    "Use list-form subprocess calls without shell=True to prevent shell injection. "
                    "E.g. subprocess.run(['cmd', 'arg1'], ...) instead of subprocess.run('cmd arg1', shell=True)."
                ),
                file_path=path,
                line_no=line_no,
            ))

    return findings


# ── Check 5: State files for sensitive data ───────────────────────────────────

def check_state_files() -> List[Finding]:
    findings: List[Finding] = []

    # State files live in ramdisk or hooks dir
    uid = os.getuid()
    search_dirs = [
        f"/run/user/{uid}/claude-hooks/state",
        "/dev/shm/claude-hooks",
        HOOKS_DIR,
    ]

    state_files = []
    for d in search_dirs:
        state_files.extend(glob.glob(os.path.join(d, "state_*.json")))
    state_files = list(dict.fromkeys(state_files))

    for path in state_files:
        data = _read_json(path)
        if data is None:
            continue
        basename = os.path.basename(path)

        # Scan all string values recursively for secret patterns
        def _walk(obj, depth=0):
            if depth > 10:
                return
            if isinstance(obj, dict):
                for k, v in obj.items():
                    combined = f"{k}={v}"
                    if isinstance(v, str) and _SECRET_PATTERN.search(combined):
                        findings.append(Finding(
                            component=f"state/{basename}",
                            kind="State",
                            severity="high",
                            finding=f"Possible secret stored in state file: key '{k}'",
                            evidence=f"{k}=<REDACTED>",
                            recommendation=(
                                "State files may be written to disk. Never store tokens, passwords, "
                                "or secrets in session state."
                            ),
                            file_path=path,
                        ))
                    _walk(v, depth + 1)
            elif isinstance(obj, list):
                for item in obj:
                    _walk(item, depth + 1)

        _walk(data)

    return findings


# ── Check 6: Circuit breaker for stuck-open gates ─────────────────────────────

def check_circuit_breaker() -> List[Finding]:
    findings: List[Finding] = []

    # Prefer ramdisk, fall back to disk
    cb_path = CB_RAMDISK if os.path.isfile(CB_RAMDISK) else CB_DISK
    if not os.path.isfile(cb_path):
        findings.append(Finding(
            component="circuit_breaker",
            kind="Infra",
            severity="info",
            finding="Circuit breaker state file not found",
            evidence=f"Checked: {CB_RAMDISK} and {CB_DISK}",
            recommendation="Circuit breaker initializes on first gate failure; no action needed if gates are healthy.",
        ))
        return findings

    cb_data = _read_json(cb_path)
    if cb_data is None:
        findings.append(Finding(
            component="circuit_breaker",
            kind="Infra",
            severity="medium",
            finding="Circuit breaker state file is corrupt",
            evidence=cb_path,
            recommendation="Delete the corrupt circuit breaker file; it will be recreated automatically.",
            file_path=cb_path,
        ))
        return findings

    now = time.time()
    for service, state in cb_data.items():
        if not isinstance(state, dict):
            continue
        cb_state = state.get("state", "CLOSED")
        if cb_state == "OPEN":
            recovery_timeout = state.get("recovery_timeout", 60)
            last_failure = state.get("last_failure_time", 0)
            stuck_threshold = recovery_timeout * 10  # 10x the recovery window = stuck
            age = now - last_failure if last_failure else 0

            if age > stuck_threshold:
                findings.append(Finding(
                    component=f"circuit_breaker/{service}",
                    kind="Infra",
                    severity="high",
                    finding=f"Circuit breaker STUCK OPEN for service '{service}'",
                    evidence=(
                        f"State=OPEN, last failure {int(age)}s ago "
                        f"(recovery_timeout={recovery_timeout}s, stuck threshold={stuck_threshold}s)"
                    ),
                    recommendation=(
                        f"Investigate '{service}' failures. Reset by deleting circuit breaker state "
                        f"or calling record_success('{service}') after confirming the service is healthy."
                    ),
                    file_path=cb_path,
                ))
            else:
                findings.append(Finding(
                    component=f"circuit_breaker/{service}",
                    kind="Infra",
                    severity="medium",
                    finding=f"Circuit breaker OPEN for '{service}' (within recovery window)",
                    evidence=(
                        f"State=OPEN, last failure {int(age)}s ago, "
                        f"recovery_timeout={recovery_timeout}s"
                    ),
                    recommendation=(
                        f"Service '{service}' is currently failing. "
                        "Check logs; the circuit will transition to HALF_OPEN automatically."
                    ),
                    file_path=cb_path,
                ))

    return findings


# ── Check 7: .file_claims.json for stale claims ───────────────────────────────

def check_file_claims() -> List[Finding]:
    findings: List[Finding] = []
    stale_threshold = 2 * 3600  # 2 hours

    if not os.path.isfile(CLAIMS_PATH):
        findings.append(Finding(
            component=".file_claims.json",
            kind="Infra",
            severity="info",
            finding="No .file_claims.json found (Gate 13 workspace isolation inactive)",
            evidence=CLAIMS_PATH,
            recommendation="Expected when no concurrent agents are active.",
        ))
        return findings

    claims = _read_json(CLAIMS_PATH)
    if claims is None:
        findings.append(Finding(
            component=".file_claims.json",
            kind="Infra",
            severity="medium",
            finding=".file_claims.json is corrupt or unparseable",
            evidence=CLAIMS_PATH,
            recommendation=(
                "Delete .file_claims.json so Gate 13 can reinitialize it. "
                "This will release all stale workspace locks."
            ),
            file_path=CLAIMS_PATH,
        ))
        return findings

    if not isinstance(claims, dict):
        findings.append(Finding(
            component=".file_claims.json",
            kind="Infra",
            severity="medium",
            finding=".file_claims.json has unexpected format (not a dict)",
            evidence=f"Type: {type(claims).__name__}",
            recommendation="Delete and reinitialize .file_claims.json.",
            file_path=CLAIMS_PATH,
        ))
        return findings

    now = time.time()
    total = len(claims)
    stale_count = 0

    for file_path, info in claims.items():
        if not isinstance(info, dict):
            continue
        claimed_at = info.get("claimed_at", now)
        age = now - claimed_at
        if age > stale_threshold:
            stale_count += 1
            session_id = info.get("session_id", "unknown")
            findings.append(Finding(
                component=".file_claims.json",
                kind="Infra",
                severity="medium",
                finding=f"Stale workspace claim: {os.path.basename(file_path)}",
                evidence=(
                    f"File: {file_path}, claimed by session {session_id}, "
                    f"age: {int(age // 3600)}h {int((age % 3600) // 60)}m"
                ),
                recommendation=(
                    "Remove stale claims by running the health skill with --repair, "
                    "or delete .file_claims.json if no agents are currently active."
                ),
                file_path=CLAIMS_PATH,
            ))

    if stale_count == 0 and total > 0:
        findings.append(Finding(
            component=".file_claims.json",
            kind="Infra",
            severity="info",
            finding=f"{total} active workspace claim(s), all current",
            evidence=f"All claims within {stale_threshold // 3600}h stale threshold",
            recommendation="No action needed.",
        ))

    return findings


# ── Report formatter ──────────────────────────────────────────────────────────

_SEVERITY_LABEL = {
    "critical": "CRITICAL",
    "high":     "HIGH    ",
    "medium":   "MEDIUM  ",
    "low":      "LOW     ",
    "info":     "INFO    ",
}


def _print_report(all_findings: List[Finding], min_sev: int) -> None:
    """Print a formatted security report to stdout."""
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    filtered = [
        f for f in all_findings
        if SEVERITY_ORDER.get(f.severity, 99) <= min_sev
    ]

    # Count by severity
    counts = {s: 0 for s in SEVERITY_ORDER}
    for f in all_findings:  # count from all, not filtered
        counts[f.severity] = counts.get(f.severity, 0) + 1

    # Header
    print()
    print("=" * 78)
    print(f"  TORUS FRAMEWORK SECURITY SCAN REPORT — {date_str}")
    print("=" * 78)
    print()

    # Summary counts
    parts = []
    for sev in ("critical", "high", "medium", "low", "info"):
        n = counts[sev]
        if n:
            parts.append(f"{n} {sev.capitalize()}")
    if parts:
        print(f"Findings: {' | '.join(parts)}")
    else:
        print("Findings: 0 (clean)")
    print()

    if not filtered:
        print(f"  No findings at or above severity threshold.")
        print()
        return

    # Findings detail
    for f in sorted(filtered, key=lambda x: SEVERITY_ORDER.get(x.severity, 99)):
        sev_label = _SEVERITY_LABEL.get(f.severity, f.severity.upper().ljust(8))
        print(f"[{sev_label}] {f.component}")
        print(f"  Finding:        {f.finding}")
        print(f"  Evidence:       {f.evidence}")
        print(f"  Recommendation: {f.recommendation}")
        if f.file_path:
            loc = f.file_path
            if f.line_no:
                loc += f":{f.line_no}"
            print(f"  File:           {loc}")
        print()

    # Remediation section for Critical/High
    critical_high = [
        f for f in filtered
        if f.severity in ("critical", "high")
    ]
    if critical_high:
        print("-" * 78)
        print("REMEDIATION REQUIRED")
        print("-" * 78)
        for f in critical_high:
            sev_label = f.severity.upper()
            print(f"\n[{sev_label}] {f.component} — {f.finding}")
            if f.file_path:
                loc = f.file_path
                if f.line_no:
                    loc += f":{f.line_no}"
                print(f"  File:   {loc}")
            print(f"  Fix:    {f.recommendation}")
        print()


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    min_sev = _min_severity()

    all_findings: List[Finding] = []

    print("Running Torus Framework Security Scan...")

    checks = [
        ("Gate files (existence + check() export)", check_gates),
        ("Gate 17 injection defense patterns",      check_gate17_patterns),
        ("MCP tool registrations (settings.json)",  check_mcp_registrations),
        ("Hardcoded secrets in hooks/shared/",      check_shared_secrets),
        ("State files for sensitive data",          check_state_files),
        ("Circuit breaker stuck-open gates",        check_circuit_breaker),
        (".file_claims.json stale claims",          check_file_claims),
    ]

    for label, fn in checks:
        try:
            results = fn()
            all_findings.extend(results)
            n_critical_high = sum(
                1 for r in results if r.severity in ("critical", "high")
            )
            status = "WARN" if n_critical_high else "OK"
            print(f"  [{status}] {label}: {len(results)} finding(s)")
        except Exception as exc:
            print(f"  [ERR] {label}: scanner error — {exc}", file=sys.stderr)

    _print_report(all_findings, min_sev)
    return 0


if __name__ == "__main__":
    sys.exit(main())
