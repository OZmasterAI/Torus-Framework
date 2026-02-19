"""Data layer for the Torus TUI dashboard.

All file reads are fail-open — missing or corrupt files return sensible defaults.
Data is cached with a 2-second TTL to avoid hammering the filesystem.
"""

import json
import os
import time
import glob as globmod
from datetime import datetime, timezone

CLAUDE_DIR = os.path.expanduser("~/.claude")
HOOKS_DIR = os.path.join(CLAUDE_DIR, "hooks")
AUDIT_DIR = os.path.join(HOOKS_DIR, "audit")
EFFECTIVENESS_FILE = os.path.join(HOOKS_DIR, ".gate_effectiveness.json")
LIVE_STATE_FILE = os.path.join(CLAUDE_DIR, "LIVE_STATE.json")
STATS_CACHE_FILE = os.path.join(CLAUDE_DIR, "stats-cache.json")
SNAPSHOT_FILE = os.path.join(HOOKS_DIR, ".statusline_snapshot.json")
MEMORY_TS_FILE = os.path.join(HOOKS_DIR, ".memory_last_queried")
GIT_CACHE_FILE = "/tmp/statusline-git-cache"
MODES_DIR = os.path.join(CLAUDE_DIR, "modes")

# Toggle definitions: (label, json_key, default, description)
# Descriptions and defaults must match boot.py _toggles (lines 770-789)
TOGGLES = [
    ("Terminal L2 always-on",  "terminal_l2_always", False, "Always run terminal FTS5 search (OFF = only when L1 < 0.3)"),
    ("Terminal L2 enrichment", "context_enrichment",  False, "Attach ±30min terminal history to ChromaDB results"),
    ("TG L3 always-on",       "tg_l3_always",        False, "Always run Telegram FTS5 search (OFF = only when L1 < 0.3)"),
    ("TG L3 enrichment",      "tg_enrichment",       False, "Attach ±30min Telegram messages to ChromaDB results"),
    ("Telegram bot",           "tg_bot_tmux",         False, "Start/stop Telegram bot in dedicated tmux session"),
    ("Gate auto-tune",        "gate_auto_tune",      False, "Auto-adjust gate thresholds based on effectiveness data"),
    ("Budget degradation",    "budget_degradation",  False, "Auto-degrade models when approaching token budget"),
    ("Chain memory",          "chain_memory",        False, "Remember and reuse successful skill chain sequences"),
    ("Session notify",        "tg_session_notify",   False, "Send session summary to Telegram on end"),
    ("Session budget",        "session_token_budget", 0,     "Max tokens per session (0 = unlimited)"),
]


class DataLayer:
    """Cached, fail-open data reader for all framework files."""

    def __init__(self):
        self._cache = {}
        self._cache_ttl = 2.0
        self._stats_ttl = 60.0

    def _cached(self, key, ttl, loader, default=None):
        now = time.time()
        if key in self._cache:
            ts, data = self._cache[key]
            if now - ts < ttl:
                return data
        try:
            data = loader()
        except Exception:
            if key in self._cache:
                return self._cache[key][1]
            return default if default is not None else {}
        self._cache[key] = (now, data)
        return data

    def invalidate(self, key=None):
        if key:
            self._cache.pop(key, None)
        else:
            self._cache.clear()

    def live_state(self):
        def _load():
            with open(LIVE_STATE_FILE) as f:
                return json.load(f)
        return self._cached("live_state", self._cache_ttl, _load) or {}

    def get_toggle(self, key, default=None):
        return self.live_state().get(key, default)

    def set_toggle(self, key, value):
        try:
            with open(LIVE_STATE_FILE) as f:
                data = json.load(f)
            data[key] = value
            tmp = LIVE_STATE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
            os.replace(tmp, LIVE_STATE_FILE)
            self.invalidate("live_state")
            return True
        except Exception:
            return False

    def gate_effectiveness(self):
        def _load():
            if not os.path.exists(EFFECTIVENESS_FILE):
                return {}
            with open(EFFECTIVENESS_FILE) as f:
                return json.load(f)
        return self._cached("gate_eff", self._cache_ttl, _load) or {}

    def session_state(self):
        def _load():
            pattern = os.path.join(HOOKS_DIR, "state_*.json")
            files = globmod.glob(pattern)
            files = [f for f in files if not f.endswith(('.lock', '.tmp'))]
            if not files:
                return {}
            newest = max(files, key=os.path.getmtime)
            with open(newest) as f:
                return json.load(f)
        return self._cached("session_state", self._cache_ttl, _load) or {}

    def memory_stats(self):
        def _load():
            with open(STATS_CACHE_FILE) as f:
                return json.load(f)
        return self._cached("mem_stats", self._stats_ttl, _load) or {}

    def audit_tail(self, n=50):
        def _load():
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            fpath = os.path.join(AUDIT_DIR, f"{today}.jsonl")
            if not os.path.exists(fpath):
                return []
            entries = []
            with open(fpath) as f:
                lines = f.readlines()
            for line in lines[-n:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return entries
        return self._cached("audit_tail", self._cache_ttl, _load, default=[]) or []

    def activity_buckets(self, hours=24):
        def _load():
            cutoff = time.time() - (hours * 3600)
            buckets = {}
            if not os.path.isdir(AUDIT_DIR):
                return []
            for fname in sorted(os.listdir(AUDIT_DIR), reverse=True):
                if not fname.endswith(".jsonl"):
                    continue
                fpath = os.path.join(AUDIT_DIR, fname)
                try:
                    with open(fpath) as f:
                        for line in f:
                            try:
                                entry = json.loads(line.strip())
                            except json.JSONDecodeError:
                                continue
                            ts_str = entry.get("timestamp", "")
                            try:
                                dt = datetime.fromisoformat(ts_str)
                                ts = dt.timestamp()
                            except (ValueError, TypeError):
                                continue
                            if ts < cutoff:
                                continue
                            bucket = int(ts // 1800)
                            buckets[bucket] = buckets.get(bucket, 0) + 1
                except (IOError, OSError):
                    continue
            if not buckets:
                return []
            min_b = min(buckets)
            max_b = max(buckets)
            return [buckets.get(b, 0) for b in range(min_b, max_b + 1)]
        return self._cached("activity_buckets", self._cache_ttl, _load, default=[]) or []

    def block_summary(self, hours=24):
        def _load():
            cutoff = time.time() - (hours * 3600)
            gate_counts = {}
            tool_counts = {}
            total = 0
            if not os.path.isdir(AUDIT_DIR):
                return {"blocked_by_gate": {}, "blocked_by_tool": {}, "total_blocks": 0}
            for fname in sorted(os.listdir(AUDIT_DIR), reverse=True):
                if not fname.endswith(".jsonl"):
                    continue
                fpath = os.path.join(AUDIT_DIR, fname)
                try:
                    with open(fpath) as f:
                        for line in f:
                            try:
                                entry = json.loads(line.strip())
                            except json.JSONDecodeError:
                                continue
                            if entry.get("decision") != "block":
                                continue
                            ts_str = entry.get("timestamp", "")
                            try:
                                dt = datetime.fromisoformat(ts_str)
                                if dt.timestamp() < cutoff:
                                    continue
                            except (ValueError, TypeError):
                                continue
                            gate = entry.get("gate", "unknown")
                            tool = entry.get("tool", "unknown")
                            gate_counts[gate] = gate_counts.get(gate, 0) + 1
                            tool_counts[tool] = tool_counts.get(tool, 0) + 1
                            total += 1
                except (IOError, OSError):
                    continue
            return {
                "blocked_by_gate": dict(sorted(gate_counts.items(), key=lambda x: -x[1])),
                "blocked_by_tool": dict(sorted(tool_counts.items(), key=lambda x: -x[1])),
                "total_blocks": total,
            }
        return self._cached("block_summary", self._cache_ttl * 5, _load)

    def statusline_snapshot(self):
        """Read the statusline bridge snapshot (2s TTL)."""
        def _load():
            with open(SNAPSHOT_FILE) as f:
                return json.load(f)
        return self._cached("snapshot", self._cache_ttl, _load) or {}

    def memory_freshness(self):
        """Minutes since last memory query, or None."""
        def _load():
            with open(MEMORY_TS_FILE) as f:
                data = json.load(f)
            ts = data.get("timestamp", 0)
            if ts <= 0:
                return None
            return int(time.time() - ts) // 60
        return self._cached("mem_fresh", self._cache_ttl, _load, default=None)

    def git_branch(self):
        """Current git branch from statusline cache."""
        def _load():
            with open(GIT_CACHE_FILE) as f:
                return f.read().strip() or None
        return self._cached("git_branch", 10.0, _load, default=None)

    def active_mode(self):
        """Active behavioral mode name, or None."""
        def _load():
            with open(os.path.join(MODES_DIR, ".active")) as f:
                name = f.read().strip()
            if not name:
                return None
            abbrevs = {"coding": "code", "review": "rev", "debug": "dbg", "docs": "docs"}
            return abbrevs.get(name, name[:6])
        return self._cached("active_mode", self._cache_ttl, _load, default=None)

    def verification_ratio(self):
        """Return (verified, total) from session state."""
        state = self.session_state()
        verified = len(state.get("verified_fixes", []))
        pending = len(state.get("pending_verification", []))
        return (verified, verified + pending)
