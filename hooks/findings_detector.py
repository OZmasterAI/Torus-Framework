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
import sys
from datetime import datetime

REPO = os.path.expanduser("~/projects/security-findings")
DEDUP_FILE = os.path.join(REPO, ".detected_hashes")
OUTPUT_TOOLS = {"Bash", "mcp__toolshed__run_tool"}
CODE_TOOLS = {"Read", "Grep", "Edit", "Write"}
MATCH_TOOLS = OUTPUT_TOOLS | CODE_TOOLS

SKIP_PATH_SEGMENTS = {
    "node_modules",
    ".git",
    "vendor",
    "dist",
    "build",
    "__pycache__",
    ".venv",
    "venv",
    ".next",
    "security-findings",
    ".claude",
}

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

SMART_CONTRACT_PATTERNS = [
    (r"reentrancy|re-entrancy", "reentrancy", "smart-contract", "critical"),
    (
        r"unchecked\s+(external\s+)?call|unchecked\s+send",
        "unchecked-call",
        "smart-contract",
        "high",
    ),
    (
        r"delegatecall.*untrusted|untrusted.*delegatecall",
        "unsafe-delegatecall",
        "smart-contract",
        "critical",
    ),
    (
        r"tx\.origin\s+(auth|check|require|==)",
        "tx-origin-auth",
        "smart-contract",
        "high",
    ),
    (r"selfdestruct|suicide\(\)", "selfdestruct", "smart-contract", "critical"),
    (
        r"unprotected\s+(self-?destruct|initializ|upgrade)",
        "unprotected-admin",
        "smart-contract",
        "critical",
    ),
    (r"front.?running|front.?run", "front-running", "smart-contract", "high"),
    (
        r"\bMEV\b.*(?:exploit|extract|attack|vulnerab)",
        "mev-exploit",
        "smart-contract",
        "high",
    ),
    (r"storage\s+collision", "storage-collision", "smart-contract", "high"),
    (
        r"signature\s+replay|replay\s+attack",
        "signature-replay",
        "smart-contract",
        "high",
    ),
    (
        r"access\s+control.*missing|missing\s+access\s+control",
        "missing-access-control",
        "smart-contract",
        "high",
    ),
    (
        r"uninitialized\s+(storage|proxy|contract)",
        "uninitialized-storage",
        "smart-contract",
        "high",
    ),
    (
        r"oracle\s+manipulation|price\s+oracle.*manipulat",
        "oracle-manipulation",
        "smart-contract",
        "critical",
    ),
    (
        r"timestamp\s+dependence|block\.timestamp.*manipulat",
        "timestamp-dependence",
        "smart-contract",
        "medium",
    ),
    (r"gas\s+griefing|unbounded\s+loop", "gas-griefing", "smart-contract", "medium"),
]

ECONOMIC_PATTERNS = [
    (r"flash\s+loan\s+attack", "flash-loan", "economic", "critical"),
    (r"sandwich\s+attack", "sandwich-attack", "economic", "high"),
    (r"price\s+manipulation", "price-manipulation", "economic", "critical"),
    (r"liquidity\s+drain", "liquidity-drain", "economic", "critical"),
    (r"infinite\s+mint", "infinite-mint", "economic", "critical"),
    (
        r"governance\s+attack|governance\s+takeover",
        "governance-attack",
        "economic",
        "critical",
    ),
    (
        r"token\s+approval\s+exploit|unlimited\s+approval",
        "token-approval",
        "economic",
        "high",
    ),
    (r"double\s+spend", "double-spend", "economic", "critical"),
    (r"51\s*%\s*attack|majority\s+attack", "majority-attack", "economic", "critical"),
    (r"nothing.at.stake", "nothing-at-stake", "economic", "high"),
    (r"long.range\s+attack", "long-range-attack", "economic", "high"),
    (r"eclipse\s+attack", "eclipse-attack", "economic", "high"),
    (r"sybil\s+attack", "sybil-attack", "economic", "high"),
    (r"byzantine\s+fault|byzantine\s+failure", "byzantine-fault", "economic", "high"),
    (r"equivocation\s+(detect|attack|evidence)", "equivocation", "economic", "high"),
    (r"slashing\s+condition\s+violat", "slashing-violation", "economic", "high"),
    (
        r"economic\s+exploit|incentive\s+misalign",
        "incentive-misalign",
        "economic",
        "high",
    ),
    (
        r"arbitrage\s+exploit|risk.free\s+arbitrage",
        "arbitrage-exploit",
        "economic",
        "medium",
    ),
    (r"fee\s+bypass|fee\s+evasion", "fee-bypass", "economic", "high"),
    (r"inflation\s+bug|inflation\s+attack", "inflation-bug", "economic", "critical"),
]

CODE_PATTERNS_RAW = [
    # Hardcoded secrets — high confidence, low false-positive
    (
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
        "private-key-in-code",
        "security",
        "critical",
    ),
    (r"(?:AKIA|ASIA)[A-Z0-9]{16}", "aws-access-key", "security", "critical"),
    (
        r"""(?:password|passwd|secret|api_key|apikey|auth_token)\s*[=:]\s*["'][A-Za-z0-9+/=!@#$%^&*]{8,}["']""",
        "hardcoded-credential",
        "security",
        "high",
    ),
    # Command injection — user input flowing into shell
    (r"""os\.system\s*\(\s*f["']""", "cmd-injection-fstring", "security", "high"),
    (r"""os\.popen\s*\(\s*f["']""", "cmd-injection-popen", "security", "high"),
    (r"subprocess\.\w+\s*\([^)]*shell\s*=\s*True", "shell-true", "security", "high"),
    # SQL injection — string formatting in queries
    (r"""\.execute\s*\(\s*f["']""", "sql-injection-fstring", "security", "high"),
    (
        r"""\.execute\s*\(\s*["'][^"']*["']\s*%""",
        "sql-injection-percent",
        "security",
        "high",
    ),
    (
        r"""\.execute\s*\(\s*["'][^"']*["']\s*\.\s*format\s*\(""",
        "sql-injection-format",
        "security",
        "high",
    ),
    # Eval/exec with dynamic input
    (
        r"eval\s*\(\s*(?:request|req|input|params|args|data|body|user)",
        "eval-user-input",
        "security",
        "critical",
    ),
    (
        r"exec\s*\(\s*(?:request|req|input|params|args|data|body|user)",
        "exec-user-input",
        "security",
        "critical",
    ),
    # Unsafe deserialization
    (r"pickle\.loads?\s*\(", "unsafe-pickle", "security", "medium"),
    (r"yaml\.load\s*\([^)]*\)(?!\s*#)", "yaml-unsafe-load", "security", "medium"),
    (r"marshal\.loads?\s*\(", "unsafe-marshal", "security", "medium"),
    # XSS sinks
    (r"\.innerHTML\s*=\s*[^\"']", "innerHTML-dynamic", "security", "medium"),
    (r"dangerouslySetInnerHTML\s*=\s*\{", "react-dangerousHTML", "security", "medium"),
    (r"v-html\s*=", "vue-vhtml", "security", "medium"),
    (r"document\.write\s*\(", "document-write", "security", "medium"),
    # Go — sql injection + unescaped HTML
    (
        r"""fmt\.Sprintf\s*\(\s*["'](?:SELECT|INSERT|UPDATE|DELETE)""",
        "go-sql-sprintf",
        "security",
        "high",
    ),
    (r"template\.HTML\s*\(", "go-unescaped-html", "security", "medium"),
    # Weak crypto for security purposes
    (
        r"Math\.random\s*\(\).*(?:token|key|secret|password|nonce|salt|iv)\b",
        "weak-random-crypto",
        "security",
        "high",
    ),
    (
        r"random\.random\s*\(\).*(?:token|key|secret|password|nonce|salt)\b",
        "py-weak-random",
        "security",
        "high",
    ),
    # Smart contract code patterns
    (r"tx\.origin", "tx-origin-usage", "smart-contract", "high"),
    (
        r"selfdestruct\s*\(|suicide\s*\(",
        "selfdestruct-call",
        "smart-contract",
        "critical",
    ),
    (r"\.call\{value:", "low-level-call-value", "smart-contract", "medium"),
    (r"delegatecall\s*\(", "delegatecall-usage", "smart-contract", "high"),
    # --- More secrets/tokens ---
    (r"ghp_[A-Za-z0-9]{36}", "github-pat", "security", "critical"),
    (r"gho_[A-Za-z0-9]{36}", "github-oauth-token", "security", "critical"),
    (r"xox[bpsa]-[A-Za-z0-9\-]{10,}", "slack-token", "security", "critical"),
    (r"sk-[A-Za-z0-9]{20,}", "openai-secret-key", "security", "critical"),
    (r"0x[0-9a-fA-F]{64}\b", "hex-private-key-256bit", "security", "high"),
    (
        r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
        "hardcoded-jwt",
        "security",
        "high",
    ),
    (
        r"""(?:secret|token|key|credential)_?(?:key|value|str)?\s*=\s*["'][A-Za-z0-9+/=_\-]{32,}["']""",
        "long-secret-assignment",
        "security",
        "high",
    ),
    # --- Disabled security controls ---
    (r"verify\s*=\s*False", "tls-verify-disabled", "security", "high"),
    (r"InsecureSkipVerify\s*:\s*true", "go-tls-skip-verify", "security", "high"),
    (
        r"NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*[\"']?0",
        "node-tls-disabled",
        "security",
        "high",
    ),
    (
        r"CURLOPT_SSL_VERIFYPEER\s*,\s*(?:false|0|FALSE)",
        "curl-ssl-verify-off",
        "security",
        "high",
    ),
    # --- JWT weaknesses ---
    (
        r"jwt\.decode\s*\([^)]*verify\s*=\s*False",
        "jwt-no-verify",
        "security",
        "critical",
    ),
    (
        r"""algorithms\s*=\s*\[?\s*["']none["']""",
        "jwt-alg-none-code",
        "security",
        "critical",
    ),
    # --- SSRF / open redirect in code ---
    (
        r"redirect\s*\(\s*(?:req|request)\.\w+\.(?:url|path|redirect|next|return)",
        "open-redirect-code",
        "security",
        "high",
    ),
    (
        r"requests\.(?:get|post|put|delete)\s*\(\s*(?:url|user_url|target|input)",
        "ssrf-requests",
        "security",
        "high",
    ),
    (r"fetch\s*\(\s*(?:req|request|user|params)\b", "ssrf-fetch", "security", "high"),
    (
        r"http\.(?:Get|Post)\s*\(\s*(?:url|user|input|r\.)",
        "go-ssrf",
        "security",
        "high",
    ),
    (
        r"urllib\.request\.urlopen\s*\(\s*(?:url|user|input|req)",
        "py-ssrf-urllib",
        "security",
        "high",
    ),
    # --- Path traversal in code ---
    (
        r"open\s*\(\s*(?:request|req|user_input|filename)\b",
        "path-traversal-open",
        "security",
        "high",
    ),
    (
        r"(?:readFile|readFileSync)\s*\(\s*(?:req|user|params)\b",
        "path-traversal-readfile",
        "security",
        "high",
    ),
    (
        r"os\.path\.join\s*\([^,]+,\s*(?:request|req|user_input|params)\b",
        "path-join-user-input",
        "security",
        "high",
    ),
    # --- Node.js injection ---
    (
        r"child_process\.exec\s*\(\s*`",
        "node-cmd-injection-template",
        "security",
        "high",
    ),
    (
        r"child_process\.exec\s*\(\s*(?:req|user|input|params|data)\b",
        "node-cmd-injection-input",
        "security",
        "critical",
    ),
    (r"new\s+Function\s*\(", "function-constructor", "security", "high"),
    (
        r"require\s*\(\s*(?:req|user|input|params|data)\b",
        "dynamic-require",
        "security",
        "high",
    ),
    # --- Python injection ---
    (
        r"__import__\s*\(\s*(?:request|req|user|input|params)\b",
        "py-import-injection",
        "security",
        "critical",
    ),
    (
        r"render_template_string\s*\(\s*(?:request|req|user|input)\b",
        "ssti-flask",
        "security",
        "high",
    ),
    (
        r"Markup\s*\(\s*(?:request|req|user|input)\b",
        "markup-xss-flask",
        "security",
        "high",
    ),
    (
        r"Jinja2\s*\(.*autoescape\s*=\s*False",
        "jinja2-no-autoescape",
        "security",
        "medium",
    ),
    # --- Weak crypto in code ---
    (r"hashlib\.md5\s*\(", "md5-hash-usage", "security", "medium"),
    (r"hashlib\.sha1\s*\(", "sha1-hash-usage", "security", "medium"),
    (r"""createHash\s*\(\s*["']md5["']\s*\)""", "node-md5-hash", "security", "medium"),
    (
        r"""createHash\s*\(\s*["']sha1["']\s*\)""",
        "node-sha1-hash",
        "security",
        "medium",
    ),
    (r"\bDES\b.*(?:encrypt|decrypt|cipher|Cipher)", "des-usage", "security", "medium"),
    (r"\bRC4\b.*(?:encrypt|decrypt|cipher|Cipher)", "rc4-usage", "security", "medium"),
    (
        r"PBKDF2\s*\([^)]*iterations\s*=\s*[1-9]\d{0,2}[^0-9]",
        "pbkdf2-low-iterations",
        "security",
        "medium",
    ),
    # --- Go specific ---
    (r"unsafe\.Pointer", "go-unsafe-pointer", "security", "medium"),
    (r"""http\.ListenAndServe\s*\(\s*["']:""", "go-http-no-tls", "security", "medium"),
    # --- Rust specific ---
    (r"unsafe\s*\{", "rust-unsafe-block", "security", "medium"),
    # --- CORS misconfiguration in code ---
    (
        r"""Access-Control-Allow-Origin["']\s*,\s*["']\*""",
        "cors-wildcard-code",
        "security",
        "medium",
    ),
    (
        r"""cors\(\s*\{\s*origin\s*:\s*["']\*["']""",
        "cors-wildcard-config",
        "security",
        "medium",
    ),
    # --- C/C++ specific ---
    (r"(?:::)?system\s*\(", "c-system-call", "security", "high"),
    (r"(?:::)?popen\s*\(", "c-popen-call", "security", "high"),
    (r"\bsprintf\s*\(", "c-sprintf-overflow", "bugs", "medium"),
    (r"\bstrcpy\s*\(", "c-strcpy-overflow", "bugs", "medium"),
    (r"\bstrcat\s*\(", "c-strcat-overflow", "bugs", "medium"),
    (r"\bgets\s*\(", "c-gets-overflow", "bugs", "high"),
    (
        r"\batoi\s*\(\s*(?:argv|args|input|user|param)",
        "c-atoi-unchecked",
        "bugs",
        "medium",
    ),
    (r"\bfree\s*\([^)]+\).*\bfree\s*\(", "c-double-free-suspect", "security", "high"),
    (r"\bsrand\s*\(\s*(?:time|clock)", "c-weak-seed", "security", "medium"),
    (r"#\s*pragma\s+warning\s*\(\s*disable", "c-warning-suppressed", "bugs", "low"),
    # --- More Solidity/EVM ---
    (r"abi\.encodePacked\s*\(", "solidity-encodePacked", "smart-contract", "medium"),
    (r"ecrecover\s*\(", "solidity-ecrecover", "smart-contract", "medium"),
    (r"block\.timestamp", "solidity-block-timestamp", "smart-contract", "medium"),
    (
        r"block\.number\b(?!.*nonce|.*id)",
        "solidity-block-number-dep",
        "smart-contract",
        "low",
    ),
    (r"\.transfer\s*\(", "solidity-transfer", "smart-contract", "low"),
    (r"msg\.value\b", "solidity-msg-value", "smart-contract", "low"),
    (r"assembly\s*\{", "solidity-inline-assembly", "smart-contract", "medium"),
    (
        r"pragma\s+solidity\s+[\^~]?\s*0\.[0-6]\.",
        "solidity-old-compiler",
        "smart-contract",
        "medium",
    ),
    (r"\.call\s*\(", "solidity-low-level-call", "smart-contract", "medium"),
    (
        r"payable\s*\(\s*msg\.sender\s*\)",
        "solidity-payable-sender",
        "smart-contract",
        "low",
    ),
]

ALL_PATTERNS = [
    (re.compile(p, re.IGNORECASE), name, cat, sev)
    for p, name, cat, sev in SECURITY_PATTERNS
    + BUG_PATTERNS
    + SMART_CONTRACT_PATTERNS
    + ECONOMIC_PATTERNS
]

LANG_PY = {".py", ".pyw"}
LANG_JS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte"}
LANG_GO = {".go"}
LANG_RS = {".rs"}
LANG_C = {".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx"}
LANG_SOL = {".sol"}
LANG_ANY = None

# Map pattern names to their language scope
# Patterns not listed here default to LANG_ANY (run on all files)
PATTERN_LANGS = {
    # Python
    "cmd-injection-fstring": LANG_PY,
    "cmd-injection-popen": LANG_PY,
    "shell-true": LANG_PY,
    "sql-injection-fstring": LANG_PY,
    "sql-injection-percent": LANG_PY,
    "sql-injection-format": LANG_PY,
    "eval-user-input": LANG_PY | LANG_JS,
    "exec-user-input": LANG_PY,
    "unsafe-pickle": LANG_PY,
    "yaml-unsafe-load": LANG_PY,
    "unsafe-marshal": LANG_PY,
    "py-weak-random": LANG_PY,
    "py-import-injection": LANG_PY,
    "ssti-flask": LANG_PY,
    "markup-xss-flask": LANG_PY,
    "jinja2-no-autoescape": LANG_PY,
    "md5-hash-usage": LANG_PY,
    "sha1-hash-usage": LANG_PY,
    "tls-verify-disabled": LANG_PY,
    "ssrf-requests": LANG_PY,
    "py-ssrf-urllib": LANG_PY,
    "path-traversal-open": LANG_PY,
    "path-join-user-input": LANG_PY,
    # JavaScript/TypeScript
    "innerHTML-dynamic": LANG_JS,
    "react-dangerousHTML": LANG_JS,
    "vue-vhtml": LANG_JS,
    "document-write": LANG_JS,
    "weak-random-crypto": LANG_JS,
    "node-cmd-injection-template": LANG_JS,
    "node-cmd-injection-input": LANG_JS,
    "function-constructor": LANG_JS,
    "dynamic-require": LANG_JS,
    "node-md5-hash": LANG_JS,
    "node-sha1-hash": LANG_JS,
    "node-tls-disabled": LANG_JS,
    "ssrf-fetch": LANG_JS,
    "path-traversal-readfile": LANG_JS,
    # Go
    "go-sql-sprintf": LANG_GO,
    "go-unescaped-html": LANG_GO,
    "go-tls-skip-verify": LANG_GO,
    "go-ssrf": LANG_GO,
    "go-unsafe-pointer": LANG_GO,
    "go-http-no-tls": LANG_GO,
    # Rust
    "rust-unsafe-block": LANG_RS,
    # C/C++
    "c-system-call": LANG_C,
    "c-popen-call": LANG_C,
    "c-sprintf-overflow": LANG_C,
    "c-strcpy-overflow": LANG_C,
    "c-strcat-overflow": LANG_C,
    "c-gets-overflow": LANG_C,
    "c-atoi-unchecked": LANG_C,
    "c-double-free-suspect": LANG_C,
    "c-weak-seed": LANG_C,
    "c-warning-suppressed": LANG_C,
    # Solidity
    "tx-origin-usage": LANG_SOL,
    "selfdestruct-call": LANG_SOL,
    "low-level-call-value": LANG_SOL,
    "delegatecall-usage": LANG_SOL,
    "solidity-encodePacked": LANG_SOL,
    "solidity-ecrecover": LANG_SOL,
    "solidity-block-timestamp": LANG_SOL,
    "solidity-block-number-dep": LANG_SOL,
    "solidity-transfer": LANG_SOL,
    "solidity-msg-value": LANG_SOL,
    "solidity-inline-assembly": LANG_SOL,
    "solidity-old-compiler": LANG_SOL,
    "solidity-low-level-call": LANG_SOL,
    "solidity-payable-sender": LANG_SOL,
}

ALL_CODE_PATTERNS = [
    (
        re.compile(p, re.IGNORECASE if sev == "critical" else 0),
        name,
        cat,
        sev,
        PATTERN_LANGS.get(name, LANG_ANY),
    )
    for p, name, cat, sev in CODE_PATTERNS_RAW
]

CATEGORY_DIRS = {
    "security": "detected/security",
    "bugs": "detected/bugs",
    "errors": "detected/errors",
    "smart-contract": "detected/smart-contract",
    "economic": "detected/economic",
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


def _should_skip_path(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    return any(seg in SKIP_PATH_SEGMENTS for seg in parts)


def _get_code_file_path(tool_name: str, tool_input: dict) -> str:
    if tool_name in ("Read", "Edit", "Write"):
        return tool_input.get("file_path", "")
    if tool_name == "Grep":
        return tool_input.get("path", "")
    return ""


def _get_code_text(tool_name: str, tool_input: dict, response: str) -> str:
    if tool_name == "Read":
        return response
    if tool_name == "Grep":
        return response
    if tool_name == "Edit":
        return tool_input.get("new_string", "")
    if tool_name == "Write":
        return tool_input.get("content", "")
    return ""


def _scan_and_save(
    text,
    patterns,
    file_path,
    tool_name,
    project,
    session_id,
    confidence,
    file_ext=None,
):
    for entry in patterns:
        if len(entry) == 5:
            pattern, name, category, severity, langs = entry
            if langs is not None and file_ext and file_ext not in langs:
                continue
        else:
            pattern, name, category, severity = entry
        match = pattern.search(text)
        if match:
            content_hash = _fnv1a(f"{name}:{file_path}:{match.group()}")
            if _already_detected(content_hash):
                continue

            context = _extract_context(text, match.start())
            title = f"{name}-{match.group()[:40]}"
            title = re.sub(r"[^\w\s.-]", "", title).strip()

            save_detected(
                title=title,
                category=category,
                project=project,
                source_tool=tool_name,
                confidence=confidence,
                pattern_name=name,
                severity=severity,
                summary=f"Auto-detected {name} in {os.path.basename(file_path) or 'output'}: {match.group()[:80]}",
                source_output=context,
                working_dir=file_path,
                session_id=session_id,
            )
            _record_hash(content_hash)


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    if tool_name not in MATCH_TOOLS:
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    session_id = data.get("session_id", "unknown")
    project = os.path.basename(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))

    # --- Code tool scanning (Read/Edit/Write/Grep) ---
    # Handled first: Edit/Write response is a short success msg, text to scan is in tool_input
    if tool_name in CODE_TOOLS:
        raw_response = data.get("tool_response", "")
        response = (
            str(raw_response)
            if not isinstance(raw_response, dict)
            else (
                raw_response.get("content", "")
                or raw_response.get("output", "")
                or str(raw_response)
            )
        )
        file_path = _get_code_file_path(tool_name, tool_input)
        if _should_skip_path(file_path):
            sys.exit(0)
        text = _get_code_text(tool_name, tool_input, response)
        if len(text) < 10:
            sys.exit(0)
        file_ext = os.path.splitext(file_path)[1].lower()
        _scan_and_save(
            text,
            ALL_CODE_PATTERNS,
            file_path,
            tool_name,
            project,
            session_id,
            "medium",
            file_ext=file_ext,
        )
        sys.exit(0)

    # --- Output tool scanning (Bash/toolshed) ---
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

    if len(response) < 30:
        sys.exit(0)

    command = tool_input.get("command", "") if tool_name == "Bash" else ""
    if "security-findings" in command:
        sys.exit(0)

    if tool_name == "mcp__toolshed__run_tool":
        server = tool_input.get("server", "")
        if server in {"memory", "torus-skills", "search"}:
            sys.exit(0)

    working_dir = command[:100] if tool_name == "Bash" else ""
    _scan_and_save(
        response, ALL_PATTERNS, working_dir, tool_name, project, session_id, "medium"
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
