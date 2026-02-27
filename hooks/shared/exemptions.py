"""Shared tiered exemption functions for gate modules.

Three tiers, each building on the previous:
  - is_exempt_base:     null guard + basenames + skills dir (prefix match)
  - is_exempt_standard: base + test/spec file patterns
  - is_exempt_full:     standard + non-code extension filter
"""

import os

BASE_EXEMPT_BASENAMES = {"state.json", "HANDOFF.md", "LIVE_STATE.json", "CLAUDE.md", "__init__.py"}
BASE_EXEMPT_DIRS = [os.path.join(os.path.expanduser("~"), ".claude", "skills")]
STANDARD_EXEMPT_PATTERNS = ("test_", "_test.", ".test.", "spec_", "_spec.", ".spec.")
FULL_EXEMPT_EXTENSIONS = {
    ".md", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".txt",
    ".sh", ".bash", ".css", ".html", ".xml", ".csv", ".lock",
}


def is_exempt_base(file_path):
    """Tier 1: null/empty guard, exempt basenames, skills directory (prefix match)."""
    if not file_path:
        return True
    basename = os.path.basename(file_path)
    if basename in BASE_EXEMPT_BASENAMES:
        return True
    norm = os.path.normpath(file_path)
    for d in BASE_EXEMPT_DIRS:
        nd = os.path.normpath(d)
        if norm.startswith(nd + os.sep) or norm == nd:
            return True
    return False


def is_exempt_standard(file_path):
    """Tier 2: base + test/spec file patterns (case-insensitive)."""
    if is_exempt_base(file_path):
        return True
    lower = os.path.basename(file_path).lower()
    if any(pat in lower for pat in STANDARD_EXEMPT_PATTERNS):
        return True
    return False


def is_exempt_full(file_path, exempt_extensions=None):
    """Tier 3: standard + non-code extension filter."""
    if is_exempt_standard(file_path):
        return True
    ext_set = exempt_extensions if exempt_extensions is not None else FULL_EXEMPT_EXTENSIONS
    _, ext = os.path.splitext(os.path.basename(file_path))
    if ext.lower() in ext_set:
        return True
    return False
