"""Gate correlation and redundancy analysis — shared/gate_correlator.py

Analyses historical audit log data to surface relationships between gates:

1. Co-occurrence matrix   — how often pairs of gates fire on the same tool call
2. Gate chains            — gate A fires then gate B fires within a time window
3. Redundancy detection   — gates that always block or pass together
4. Optimal gate ordering  — fastest-reject-first recommendation based on block
                            rate and co-occurrence patterns

All analysis is read-only. This module never modifies gate configuration.

Data sources
------------
- /home/crab/.claude/hooks/.gate_effectiveness.json  (lifetime block counts)
- /home/crab/.claude/hooks/audit/YYYY-MM-DD.jsonl    (per-decision audit trail)
- /home/crab/.claude/hooks/.audit_trail.jsonl         (persistent append trail)

Typical usage
-------------
    from shared.gate_correlator import GateCorrelator

    correlator = GateCorrelator()
    report = correlator.full_report()
    print(report["summary"])
"""

import gzip
import json
import os
from collections import defaultdict
from datetime import datetime
from typing import Dict, Iterator, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HOOKS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks")
_EFFECTIVENESS_FILE = os.path.join(_HOOKS_DIR, ".gate_effectiveness.json")
_AUDIT_TRAIL = os.path.join(_HOOKS_DIR, ".audit_trail.jsonl")
_AUDIT_DIR = os.path.join(_HOOKS_DIR, "audit")

# Window (seconds) within which gate B is considered chained after gate A
CHAIN_WINDOW_SECONDS = 5.0

# Minimum number of co-occurrences required before a pair is considered
# meaningful for redundancy / chain analysis.
MIN_COOCCURRENCE = 3

# Minimum Jaccard similarity to flag two gates as "possibly redundant"
REDUNDANCY_JACCARD_THRESHOLD = 0.85

# ---------------------------------------------------------------------------
# Gate name normalisation (mirrors audit_log._GATE_NAME_MAP)
# ---------------------------------------------------------------------------

_GATE_NAME_MAP: Dict[str, str] = {
    # Full module path form (used in audit log entries)
    "gates.gate_01_read_before_edit":    "GATE 1: READ BEFORE EDIT",
    "gates.gate_02_no_destroy":          "GATE 2: NO DESTROY",
    "gates.gate_03_test_before_deploy":  "GATE 3: TEST BEFORE DEPLOY",
    "gates.gate_04_memory_first":        "GATE 4: MEMORY FIRST",
    "gates.gate_05_proof_before_fixed":  "GATE 5: PROOF BEFORE FIXED",
    "gates.gate_06_save_fix":            "GATE 6: SAVE TO MEMORY",
    "gates.gate_07_critical_file_guard": "GATE 7: CRITICAL FILE GUARD",
    "gates.gate_08_temporal":            "GATE 8: TEMPORAL AWARENESS",
    "gates.gate_09_strategy_ban":        "GATE 9: STRATEGY BAN",
    "gates.gate_10_model_enforcement":   "GATE 10: MODEL COST GUARD",
    "gates.gate_11_rate_limit":          "GATE 11: RATE LIMIT",
    # gate_12 MERGED into gate_06 — removed
    "gates.gate_13_workspace_isolation": "GATE 13: WORKSPACE ISOLATION",
    "gates.gate_14_confidence_check":    "GATE 14: CONFIDENCE CHECK",
    "gates.gate_15_causal_chain":        "GATE 15: CAUSAL CHAIN ENFORCEMENT",
    "gates.gate_16_code_quality":        "GATE 16: CODE QUALITY",
    "gates.gate_17_injection_defense":   "GATE 17: INJECTION DEFENSE",
    # Short form (keys in .gate_effectiveness.json, no package prefix)
    "gate_01_read_before_edit":          "GATE 1: READ BEFORE EDIT",
    "gate_02_no_destroy":                "GATE 2: NO DESTROY",
    "gate_03_test_before_deploy":        "GATE 3: TEST BEFORE DEPLOY",
    "gate_04_memory_first":              "GATE 4: MEMORY FIRST",
    "gate_05_proof_before_fixed":        "GATE 5: PROOF BEFORE FIXED",
    "gate_06_save_fix":                  "GATE 6: SAVE TO MEMORY",
    "gate_07_critical_file_guard":       "GATE 7: CRITICAL FILE GUARD",
    "gate_08_temporal":                  "GATE 8: TEMPORAL AWARENESS",
    "gate_09_strategy_ban":              "GATE 9: STRATEGY BAN",
    "gate_10_model_enforcement":         "GATE 10: MODEL COST GUARD",
    "gate_11_rate_limit":                "GATE 11: RATE LIMIT",
    # gate_12 MERGED into gate_06 — removed
    "gate_13_workspace_isolation":       "GATE 13: WORKSPACE ISOLATION",
    "gate_14_confidence_check":          "GATE 14: CONFIDENCE CHECK",
    "gate_15_causal_chain":              "GATE 15: CAUSAL CHAIN ENFORCEMENT",
    "gate_16_code_quality":              "GATE 16: CODE QUALITY",
    "gate_17_injection_defense":         "GATE 17: INJECTION DEFENSE",
}

# Canonical gate ordering (module-name order from enforcer.py GATE_MODULES)
_CANONICAL_ORDER: List[str] = [
    "GATE 1: READ BEFORE EDIT",
    "GATE 2: NO DESTROY",
    "GATE 3: TEST BEFORE DEPLOY",
    "GATE 4: MEMORY FIRST",
    "GATE 5: PROOF BEFORE FIXED",
    "GATE 6: SAVE TO MEMORY",
    "GATE 7: CRITICAL FILE GUARD",
    "GATE 9: STRATEGY BAN",
    "GATE 10: MODEL COST GUARD",
    "GATE 11: RATE LIMIT",
    "GATE 13: WORKSPACE ISOLATION",
    "GATE 14: CONFIDENCE CHECK",
    "GATE 15: CAUSAL CHAIN ENFORCEMENT",
    "GATE 16: CODE QUALITY",
    "GATE 17: INJECTION DEFENSE",
]

# Tier 1 gates that must always stay first regardless of ordering suggestions
_TIER1_GATES: Set[str] = {
    "GATE 1: READ BEFORE EDIT",
    "GATE 2: NO DESTROY",
    "GATE 3: TEST BEFORE DEPLOY",
}


def _normalize_gate(name: str) -> str:
    """Return canonical gate display name, passing through if already canonical."""
    return _GATE_NAME_MAP.get(name, name)


# ---------------------------------------------------------------------------
# Audit log loading
# ---------------------------------------------------------------------------

def _iter_audit_entries(max_entries: int = 50_000) -> Iterator[dict]:
    """Yield audit log entries from all available sources.

    Reads .audit_trail.jsonl first (cheapest, all sessions), then falls
    back to daily JSONL files in audit/ sorted by mtime.

    Yields dicts with at least: gate, tool, decision, timestamp.
    Silently skips malformed lines. Deduplicates by ULID id field.
    """
    seen_ids: Set[str] = set()
    count = 0

    def _yield_from_file(path: str, gzipped: bool = False) -> Iterator[dict]:
        nonlocal count
        if count >= max_entries:
            return
        try:
            if gzipped:
                fh = gzip.open(path, "rt", encoding="utf-8", errors="replace")
            else:
                fh = open(path, "r", encoding="utf-8", errors="replace")
            with fh:
                for raw in fh:
                    if count >= max_entries:
                        return
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        entry = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(entry, dict):
                        continue
                    entry_id = entry.get("id")
                    if entry_id:
                        if entry_id in seen_ids:
                            continue
                        seen_ids.add(entry_id)
                    raw_gate = entry.get("gate", "")
                    entry["gate"] = _normalize_gate(raw_gate)
                    count += 1
                    yield entry
        except (IOError, OSError, gzip.BadGzipFile):
            pass

    # 1. Persistent audit trail (append-only, all sessions)
    if os.path.isfile(_AUDIT_TRAIL):
        yield from _yield_from_file(_AUDIT_TRAIL)

    # 2. Daily JSONL files (newest first to avoid re-counting recent data)
    if os.path.isdir(_AUDIT_DIR) and count < max_entries:
        day_files = []
        for fname in os.listdir(_AUDIT_DIR):
            if not (fname.endswith(".jsonl") or fname.endswith(".jsonl.gz")):
                continue
            fpath = os.path.join(_AUDIT_DIR, fname)
            try:
                mtime = os.path.getmtime(fpath)
                day_files.append((mtime, fpath))
            except OSError:
                continue
        day_files.sort(reverse=True)
        for _, fpath in day_files:
            if count >= max_entries:
                break
            yield from _yield_from_file(fpath, gzipped=fpath.endswith(".gz"))


def _load_effectiveness() -> Dict[str, Dict[str, int]]:
    """Load lifetime gate effectiveness counters from JSON file.

    Returns dict mapping gate_key -> {"blocks": N, "overrides": N, "prevented": N}.
    Returns empty dict on any error.
    """
    try:
        with open(_EFFECTIVENESS_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (IOError, OSError, json.JSONDecodeError):
        pass
    return {}


# ---------------------------------------------------------------------------
# Core helper: group audit entries by logical tool-call batch
# ---------------------------------------------------------------------------

def _ts_float(entry: dict) -> float:
    """Parse ISO timestamp from an audit entry to a float epoch."""
    ts = entry.get("timestamp", "")
    try:
        return datetime.fromisoformat(ts).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _group_by_tool_call(entries: List[dict]) -> List[List[dict]]:
    """Group audit entries into per-tool-call batches.

    Multiple gates fire on one tool call within milliseconds.  We group
    consecutive entries that share (session_id, tool) and are within 1 second
    of each other.

    Returns a list of groups; each group is a non-empty list of entry dicts.
    """
    entries_sorted = sorted(entries, key=_ts_float)

    groups: List[List[dict]] = []
    current: List[dict] = []
    last_ts = -1.0
    last_session: Optional[str] = None
    last_tool: Optional[str] = None

    for entry in entries_sorted:
        ts = _ts_float(entry)
        session = entry.get("session_id", "")
        tool = entry.get("tool", "")
        gap = ts - last_ts if last_ts >= 0 else 0.0

        if (
            not current
            or gap > 1.0
            or session != last_session
            or tool != last_tool
        ):
            if current:
                groups.append(current)
            current = [entry]
        else:
            current.append(entry)

        last_ts = ts
        last_session = session
        last_tool = tool

    if current:
        groups.append(current)

    return groups


# ---------------------------------------------------------------------------
# Feature 1: Co-occurrence matrix
# ---------------------------------------------------------------------------

def build_cooccurrence_matrix(
    entries: List[dict],
) -> Dict[Tuple[str, str], int]:
    """Count how many tool calls triggered both gate A and gate B.

    The result is symmetric: pair (A, B) is stored with A < B lexicographically.
    Only gates that both fired (any decision) on the same tool call are counted.

    Args:
        entries: Pre-loaded audit log entry dicts.

    Returns:
        Dict mapping (gate_a, gate_b) -> co-occurrence count.
    """
    groups = _group_by_tool_call(entries)
    counts: Dict[Tuple[str, str], int] = defaultdict(int)

    for group in groups:
        unique_gates: List[str] = list(
            dict.fromkeys(e.get("gate", "") for e in group if e.get("gate"))
        )
        for i, gate_a in enumerate(unique_gates):
            for gate_b in unique_gates[i + 1:]:
                key = (min(gate_a, gate_b), max(gate_a, gate_b))
                counts[key] += 1

    return dict(counts)


def cooccurrence_summary(matrix: Dict[Tuple[str, str], int]) -> List[dict]:
    """Convert co-occurrence matrix to a sorted, human-readable list.

    Args:
        matrix: Output of build_cooccurrence_matrix().

    Returns:
        List of dicts sorted by count descending, each with gate_a, gate_b, count.
    """
    return [
        {"gate_a": a, "gate_b": b, "count": c}
        for (a, b), c in sorted(matrix.items(), key=lambda kv: kv[1], reverse=True)
    ]


# ---------------------------------------------------------------------------
# Feature 2: Gate chains (A fires -> B fires within window)
# ---------------------------------------------------------------------------

def detect_gate_chains(
    entries: List[dict],
    window_seconds: float = CHAIN_WINDOW_SECONDS,
    min_count: int = MIN_COOCCURRENCE,
) -> List[dict]:
    """Find directed gate chains: gate A fires then gate B fires soon after.

    A chain is counted when gate B fires within `window_seconds` after gate A
    within the same session.  This is directional: A->B and B->A are counted
    separately.

    Args:
        entries:        Audit log entries (any order).
        window_seconds: Maximum gap between A and B for a chain to register.
        min_count:      Minimum occurrences to include in output.

    Returns:
        List of dicts sorted by count descending:
          - from_gate: str
          - to_gate: str
          - count: int
          - avg_gap_ms: float  (mean milliseconds between A and B)
          - example_tool: str  (most common tool associated with the chain)
    """
    sorted_entries = sorted(
        entries, key=lambda e: (e.get("session_id", ""), _ts_float(e))
    )

    by_session: Dict[str, List[dict]] = defaultdict(list)
    for e in sorted_entries:
        by_session[e.get("session_id", "__global__")].append(e)

    chain_gaps: Dict[Tuple[str, str], List[float]] = defaultdict(list)
    chain_tools: Dict[Tuple[str, str], List[str]] = defaultdict(list)

    for session_entries in by_session.values():
        for i, a_entry in enumerate(session_entries):
            a_gate = a_entry.get("gate", "")
            a_ts = _ts_float(a_entry)
            if not a_gate:
                continue
            for b_entry in session_entries[i + 1:]:
                b_ts = _ts_float(b_entry)
                gap = b_ts - a_ts
                if gap > window_seconds:
                    break
                if gap < 0:
                    continue
                b_gate = b_entry.get("gate", "")
                if not b_gate or b_gate == a_gate:
                    continue
                key = (a_gate, b_gate)
                chain_gaps[key].append(gap * 1000.0)
                chain_tools[key].append(b_entry.get("tool", ""))

    results = []
    for (from_gate, to_gate), gaps in chain_gaps.items():
        if len(gaps) < min_count:
            continue
        tool_counts: Dict[str, int] = defaultdict(int)
        for t in chain_tools[(from_gate, to_gate)]:
            if t:
                tool_counts[t] += 1
        example_tool = max(tool_counts, key=tool_counts.__getitem__) if tool_counts else ""
        results.append({
            "from_gate": from_gate,
            "to_gate": to_gate,
            "count": len(gaps),
            "avg_gap_ms": round(sum(gaps) / len(gaps), 1),
            "example_tool": example_tool,
        })

    results.sort(key=lambda r: r["count"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Feature 3: Redundancy detection
# ---------------------------------------------------------------------------

def detect_redundant_gates(
    entries: List[dict],
    min_cooccurrence: int = MIN_COOCCURRENCE,
    jaccard_threshold: float = REDUNDANCY_JACCARD_THRESHOLD,
) -> List[dict]:
    """Find gate pairs that fire on near-identical sets of tool calls.

    Two gates are flagged as redundancy candidates when:
    - Jaccard(A, B) >= jaccard_threshold  (high coverage overlap)
    - They also agree on block/pass decisions at a measurable rate.

    Jaccard(A, B) = |calls where both fired| / |calls where either fired|

    Agreement rate = fraction of jointly-fired calls where both gates
    reached the same block-or-not verdict.

    Args:
        entries:           Audit log entry dicts.
        min_cooccurrence:  Minimum joint fires before analysis is run.
        jaccard_threshold: Minimum Jaccard similarity (0.0-1.0).

    Returns:
        List of dicts sorted by jaccard_similarity descending:
          - gate_a: str
          - gate_b: str
          - jaccard_similarity: float
          - agreement_rate: float
          - cooccurrence_count: int
          - note: str
    """
    groups = _group_by_tool_call(entries)

    gate_group_indices: Dict[str, Set[int]] = defaultdict(set)
    gate_decisions: Dict[str, Dict[int, str]] = defaultdict(dict)

    for idx, group in enumerate(groups):
        for entry in group:
            g = entry.get("gate", "")
            if not g:
                continue
            gate_group_indices[g].add(idx)
            current = gate_decisions[g].get(idx, "pass")
            decision = entry.get("decision", "pass")
            priority = {"block": 2, "warn": 1, "pass": 0}
            if priority.get(decision, 0) > priority.get(current, 0):
                gate_decisions[g][idx] = decision

    all_gates = sorted(gate_group_indices.keys())
    results = []

    for i, gate_a in enumerate(all_gates):
        for gate_b in all_gates[i + 1:]:
            set_a = gate_group_indices[gate_a]
            set_b = gate_group_indices[gate_b]
            intersection = set_a & set_b
            union = set_a | set_b

            cooc = len(intersection)
            if cooc < min_cooccurrence:
                continue

            jaccard = cooc / len(union) if union else 0.0
            if jaccard < jaccard_threshold:
                continue

            dec_a = gate_decisions[gate_a]
            dec_b = gate_decisions[gate_b]
            agreed = sum(
                1 for idx in intersection
                if (dec_a.get(idx, "pass") == "block") == (dec_b.get(idx, "pass") == "block")
            )
            agreement_rate = agreed / cooc if cooc > 0 else 0.0

            if jaccard >= 0.95 and agreement_rate >= 0.95:
                note = "Near-identical coverage and decisions — strong redundancy candidate"
            elif jaccard >= 0.85 and agreement_rate >= 0.85:
                note = "High overlap in coverage and decisions — possible redundancy"
            elif jaccard >= 0.85:
                note = "High coverage overlap but different decisions — complementary gates"
            else:
                note = "Moderate overlap"

            results.append({
                "gate_a": gate_a,
                "gate_b": gate_b,
                "jaccard_similarity": round(jaccard, 4),
                "agreement_rate": round(agreement_rate, 4),
                "cooccurrence_count": cooc,
                "note": note,
            })

    results.sort(key=lambda r: r["jaccard_similarity"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Feature 4: Optimal gate ordering
# ---------------------------------------------------------------------------

def optimize_gate_order(
    entries: List[dict],
    effectiveness_data: Optional[Dict[str, Dict[str, int]]] = None,
    target_tool: Optional[str] = None,
) -> List[dict]:
    """Suggest a fastest-reject-first gate ordering.

    Strategy
    --------
    1. Tier 1 gates (1, 2, 3) are pinned to front in canonical order.
       They are safety-critical and cannot be reordered.
    2. Remaining gates are scored:
         score = block_rate * 0.6 + latency_proxy * 0.4
       where latency_proxy = 1/(canonical_rank + 1) (earlier = lighter).
    3. Free (non-Tier-1) gates are sorted by score descending.
    4. Lifetime effectiveness data from .gate_effectiveness.json is used
       to augment sparse recent audit history.

    Args:
        entries:            Audit log entries.
        effectiveness_data: Lifetime effectiveness dict (loads from disk if None).
        target_tool:        Restrict analysis to this tool name (optional).

    Returns:
        List of dicts in suggested order:
          - rank: int
          - gate: str
          - block_rate: float
          - total_fires: int
          - blocks: int
          - pinned: bool
          - score: float
          - reason: str
    """
    relevant = [e for e in entries if e.get("tool") == target_tool] if target_tool else entries

    gate_fires: Dict[str, int] = defaultdict(int)
    gate_blocks: Dict[str, int] = defaultdict(int)

    for entry in relevant:
        g = entry.get("gate", "")
        if not g:
            continue
        gate_fires[g] += 1
        if entry.get("decision") == "block":
            gate_blocks[g] += 1

    if effectiveness_data is None:
        effectiveness_data = _load_effectiveness()

    for raw_key, eff in effectiveness_data.items():
        canonical = _normalize_gate(raw_key)
        eff_blocks = eff.get("blocks", 0) + eff.get("block", 0)
        if eff_blocks > gate_blocks.get(canonical, 0):
            implied_fires = max(eff_blocks * 10, gate_fires.get(canonical, 1))
            gate_fires[canonical] = max(gate_fires.get(canonical, 0), implied_fires)
            gate_blocks[canonical] = max(gate_blocks.get(canonical, 0), eff_blocks)

    all_known_gates: List[str] = list(
        dict.fromkeys(_CANONICAL_ORDER + sorted(gate_fires.keys()))
    )

    rows = []
    for gate in all_known_gates:
        fires = gate_fires.get(gate, 0)
        blocks = gate_blocks.get(gate, 0)
        block_rate = (blocks / fires) if fires > 0 else 0.0
        pinned = gate in _TIER1_GATES
        canonical_idx = (
            _CANONICAL_ORDER.index(gate) if gate in _CANONICAL_ORDER
            else len(_CANONICAL_ORDER)
        )
        latency_proxy = 1.0 / (canonical_idx + 1)
        score = block_rate * 0.6 + latency_proxy * 0.4

        rows.append({
            "gate": gate,
            "block_rate": round(block_rate, 4),
            "total_fires": fires,
            "blocks": blocks,
            "pinned": pinned,
            "score": round(score, 4),
            "_canonical_idx": canonical_idx,
        })

    pinned_rows = sorted(
        [r for r in rows if r["pinned"]], key=lambda r: r["_canonical_idx"]
    )
    free_rows = sorted(
        [r for r in rows if not r["pinned"]],
        key=lambda r: (-r["score"], r["_canonical_idx"]),
    )

    result = []
    for rank, row in enumerate(pinned_rows + free_rows, start=1):
        if row["pinned"]:
            reason = "Tier 1 safety gate — must run first (non-negotiable)"
        elif row["block_rate"] >= 0.5:
            reason = f"High block rate ({row['block_rate']:.0%}) — reject-fast candidate"
        elif row["block_rate"] >= 0.2:
            reason = f"Moderate block rate ({row['block_rate']:.0%})"
        elif row["total_fires"] == 0:
            reason = "No data — placed at canonical position"
        else:
            reason = f"Low block rate ({row['block_rate']:.0%}) — placed toward end"

        result.append({
            "rank": rank,
            "gate": row["gate"],
            "block_rate": row["block_rate"],
            "total_fires": row["total_fires"],
            "blocks": row["blocks"],
            "pinned": row["pinned"],
            "score": row["score"],
            "reason": reason,
        })

    return result


# ---------------------------------------------------------------------------
# GateCorrelator: main public class
# ---------------------------------------------------------------------------

class GateCorrelator:
    """Unified interface for gate correlation analysis.

    Loads audit data once on construction (lazily, on first access).
    All analysis results are cached after first computation.

    Parameters
    ----------
    max_entries:
        Maximum audit entries to load (default 50,000).
    """

    def __init__(self, max_entries: int = 50_000) -> None:
        self._max_entries = max_entries
        self._entries: Optional[List[dict]] = None
        self._effectiveness: Optional[Dict[str, Dict[str, int]]] = None
        self._cooccurrence: Optional[Dict[Tuple[str, str], int]] = None
        self._chains: Optional[List[dict]] = None
        self._redundant: Optional[List[dict]] = None
        self._ordering: Optional[List[dict]] = None

    def load(self) -> "GateCorrelator":
        """Eagerly load audit and effectiveness data from disk."""
        if self._entries is None:
            self._entries = list(_iter_audit_entries(self._max_entries))
        if self._effectiveness is None:
            self._effectiveness = _load_effectiveness()
        return self

    @property
    def entries(self) -> List[dict]:
        if self._entries is None:
            self.load()
        return self._entries  # type: ignore[return-value]

    @property
    def effectiveness(self) -> Dict[str, Dict[str, int]]:
        if self._effectiveness is None:
            self.load()
        return self._effectiveness  # type: ignore[return-value]

    def cooccurrence_matrix(self) -> Dict[Tuple[str, str], int]:
        """Return (cached) gate co-occurrence matrix.

        Returns:
            Dict mapping (gate_a, gate_b) -> count of tool calls where both
            gates fired.  Keys are lexicographically sorted pairs.
        """
        if self._cooccurrence is None:
            self._cooccurrence = build_cooccurrence_matrix(self.entries)
        return self._cooccurrence

    def gate_chains(
        self,
        window_seconds: float = CHAIN_WINDOW_SECONDS,
        min_count: int = MIN_COOCCURRENCE,
    ) -> List[dict]:
        """Return (cached) directed gate chain list.

        Args:
            window_seconds: Maximum gap (seconds) between A and B.
            min_count:      Minimum occurrences to include.

        Returns:
            List of chain dicts sorted by count descending.
        """
        if self._chains is None:
            self._chains = detect_gate_chains(
                self.entries,
                window_seconds=window_seconds,
                min_count=min_count,
            )
        return self._chains

    def redundant_gates(
        self,
        jaccard_threshold: float = REDUNDANCY_JACCARD_THRESHOLD,
        min_cooccurrence: int = MIN_COOCCURRENCE,
    ) -> List[dict]:
        """Return (cached) redundancy candidate list.

        Args:
            jaccard_threshold: Minimum Jaccard similarity (0.0-1.0).
            min_cooccurrence:  Minimum co-occurrences to consider.

        Returns:
            List of redundancy dicts sorted by jaccard_similarity descending.
        """
        if self._redundant is None:
            self._redundant = detect_redundant_gates(
                self.entries,
                min_cooccurrence=min_cooccurrence,
                jaccard_threshold=jaccard_threshold,
            )
        return self._redundant

    def optimize_gate_order(
        self, target_tool: Optional[str] = None
    ) -> List[dict]:
        """Return (cached) suggested gate ordering.

        Args:
            target_tool: If given, focus ordering on this tool's data.

        Returns:
            Ordered list of gate dicts: rank, gate, block_rate, score,
            pinned, reason.
        """
        if self._ordering is None:
            self._ordering = optimize_gate_order(
                self.entries,
                effectiveness_data=self.effectiveness,
                target_tool=target_tool,
            )
        return self._ordering

    def full_report(self, target_tool: Optional[str] = None) -> dict:
        """Run all four analyses and return a combined report.

        Args:
            target_tool: If given, gate ordering is computed for this tool only.

        Returns:
            Dict with keys:
              - entries_analyzed: int
              - cooccurrence: list[dict]   (sorted matrix rows)
              - gate_chains: list[dict]
              - redundant_gates: list[dict]
              - optimal_ordering: list[dict]
              - summary: str               (plain-text executive summary)
        """
        cooc = self.cooccurrence_matrix()
        chains = self.gate_chains()
        redundant = self.redundant_gates()
        ordering = self.optimize_gate_order(target_tool=target_tool)
        cooc_list = cooccurrence_summary(cooc)

        lines = [
            f"Gate Correlation Report  ({len(self.entries):,} audit entries)",
            "=" * 70,
        ]

        lines.append("\nTop co-occurrences (same tool call):")
        if cooc_list:
            for row in cooc_list[:5]:
                lines.append(
                    f"  {row['gate_a']}  +  {row['gate_b']}  =>  {row['count']} times"
                )
        else:
            lines.append("  (insufficient data)")

        lines.append("\nTop gate chains (A fires -> B fires within 5 s):")
        if chains:
            for row in chains[:5]:
                lines.append(
                    f"  {row['from_gate']}  ->  {row['to_gate']}"
                    f"  ({row['count']} times, avg {row['avg_gap_ms']:.0f} ms)"
                )
        else:
            lines.append("  No chains detected above threshold")

        lines.append("\nRedundancy candidates:")
        if redundant:
            for row in redundant[:5]:
                lines.append(
                    f"  {row['gate_a']}  ~  {row['gate_b']}"
                    f"  (Jaccard={row['jaccard_similarity']:.2f},"
                    f" agreement={row['agreement_rate']:.0%})"
                )
                lines.append(f"    {row['note']}")
        else:
            lines.append("  No redundant gate pairs detected")

        tool_label = f" (tool={target_tool})" if target_tool else " (all tools)"
        lines.append(f"\nSuggested gate order{tool_label}:")
        for row in ordering:
            pin = " [PINNED]" if row["pinned"] else ""
            lines.append(
                f"  {row['rank']:>2}. {row['gate']}{pin}"
                f"  block_rate={row['block_rate']:.0%}  score={row['score']:.3f}"
            )

        lines.append("\n" + "=" * 70)

        return {
            "entries_analyzed": len(self.entries),
            "cooccurrence": cooc_list,
            "gate_chains": chains,
            "redundant_gates": redundant,
            "optimal_ordering": ordering,
            "summary": "\n".join(lines),
        }
