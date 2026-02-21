"""Experience archive for fix pattern learning in the Torus Framework.

Stores fix attempts as CSV rows and provides query functions to surface the
best strategies for a given error type and to compute per-strategy success
rates.

File: hooks/.experience_archive.csv
Columns: timestamp, error_type, gate_id, fix_strategy, outcome, file, duration_s

Design constraints:
- Thread-safe writes via fcntl file locking (LOCK_EX).
- Fail-open: all public functions swallow exceptions so they cannot interfere
  with gate enforcement.
- atomic tmp-then-rename writes are NOT used here because we append rows; the
  lock ensures only one writer at a time.
- query functions read the whole CSV under a shared lock (LOCK_SH) so they
  never see a half-written row.
"""

import csv
import fcntl
import os
from datetime import datetime, timezone
from typing import Dict, List, Tuple


# ── Path constant ──────────────────────────────────────────────────────────────

ARCHIVE_PATH = os.path.join(
    os.path.expanduser("~"), ".claude", "hooks", ".experience_archive.csv"
)

# CSV column order (also used as header row)
_COLUMNS = ["timestamp", "error_type", "gate_id", "fix_strategy", "outcome", "file", "duration_s"]

# Valid outcome values
OUTCOME_SUCCESS = "success"
OUTCOME_FAILURE = "failure"
OUTCOME_PARTIAL = "partial"
_VALID_OUTCOMES = {OUTCOME_SUCCESS, OUTCOME_FAILURE, OUTCOME_PARTIAL}


# ── Internal helpers ───────────────────────────────────────────────────────────

def _ensure_header(path: str) -> None:
    """Create the CSV file with a header row if it does not yet exist.

    Called before every write; cheap no-op when the file already exists.
    """
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(_COLUMNS)


def _read_rows(path: str) -> List[Dict[str, str]]:
    """Read all data rows from the CSV under a shared lock.

    Returns a list of dicts keyed by column name.
    Returns [] if the file does not exist or cannot be read.
    """
    if not os.path.exists(path):
        return []
    rows: List[Dict[str, str]] = []
    try:
        with open(path, "r", newline="") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                reader = csv.DictReader(f)
                for row in reader:
                    rows.append(dict(row))
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except (OSError, csv.Error):
        pass
    return rows


# ── Public API ─────────────────────────────────────────────────────────────────

def record_fix(
    error_type: str,
    strategy: str,
    outcome: str,
    file: str = "",
    gate_id: str = "",
    duration_s: float = 0.0,
) -> bool:
    """Append one fix attempt row to the experience archive.

    Args:
        error_type: Short description of the error class, e.g. "ImportError".
        strategy:   Name of the fix strategy applied, e.g. "add-missing-import".
        outcome:    One of "success", "failure", or "partial".
        file:       File path where the fix was applied (optional).
        gate_id:    Gate that triggered the fix attempt, e.g. "gate_15" (optional).
        duration_s: Wall-clock seconds the fix attempt took (default 0.0).

    Returns:
        True on success, False if the write failed.
    """
    try:
        path = ARCHIVE_PATH
        _ensure_header(path)

        if outcome not in _VALID_OUTCOMES:
            outcome = OUTCOME_FAILURE

        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error_type": str(error_type)[:256],
            "gate_id": str(gate_id)[:64],
            "fix_strategy": str(strategy)[:256],
            "outcome": outcome,
            "file": str(file)[:512],
            "duration_s": f"{float(duration_s):.3f}",
        }

        with open(path, "a", newline="") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                writer = csv.DictWriter(f, fieldnames=_COLUMNS)
                writer.writerow(row)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        return True

    except Exception:
        return False


def query_best_strategy(error_type: str) -> str:
    """Return the fix strategy with the highest success rate for error_type.

    Considers only rows where error_type matches (case-insensitive substring).
    Among strategies with at least one attempt, ranks by success_rate then by
    total attempts (more data = more confidence). Returns "" if no data exists.

    Args:
        error_type: The error type to look up (substring match, case-insensitive).

    Returns:
        The strategy name string, or "" if no relevant history found.
    """
    try:
        rows = _read_rows(ARCHIVE_PATH)
        if not rows:
            return ""

        needle = error_type.lower()

        # Aggregate per strategy: {strategy: [total, successes]}
        stats: Dict[str, List[int]] = {}
        for row in rows:
            et = row.get("error_type", "")
            if needle not in et.lower():
                continue
            strat = row.get("fix_strategy", "").strip()
            if not strat:
                continue
            outcome = row.get("outcome", "")
            if strat not in stats:
                stats[strat] = [0, 0]  # [total, successes]
            stats[strat][0] += 1
            if outcome == OUTCOME_SUCCESS:
                stats[strat][1] += 1

        if not stats:
            return ""

        # Sort by (success_rate DESC, total_attempts DESC)
        def _rank(item: Tuple[str, List[int]]) -> Tuple[float, int]:
            _, (total, successes) = item
            rate = successes / total if total > 0 else 0.0
            return (rate, total)

        best = max(stats.items(), key=_rank)
        return best[0]

    except Exception:
        return ""


def get_success_rate(strategy: str) -> float:
    """Return the overall success rate for a given fix strategy.

    Args:
        strategy: Exact strategy name (case-sensitive).

    Returns:
        Float in [0.0, 1.0]. Returns 0.0 if the strategy has never been tried
        or if data cannot be read.
    """
    try:
        rows = _read_rows(ARCHIVE_PATH)
        if not rows:
            return 0.0

        total = 0
        successes = 0
        for row in rows:
            if row.get("fix_strategy", "").strip() != strategy:
                continue
            total += 1
            if row.get("outcome", "") == OUTCOME_SUCCESS:
                successes += 1

        if total == 0:
            return 0.0
        return successes / total

    except Exception:
        return 0.0


def get_archive_stats() -> dict:
    """Return aggregate statistics about the experience archive.

    Returns a dict with:
        total_rows:      int   — total fix attempts recorded
        unique_errors:   int   — distinct error_type values
        unique_strategies: int — distinct fix_strategy values
        overall_success_rate: float — fraction of all attempts that succeeded
        top_strategies:  list  — up to 5 strategies sorted by success_rate desc
    """
    try:
        rows = _read_rows(ARCHIVE_PATH)
        if not rows:
            return {
                "total_rows": 0,
                "unique_errors": 0,
                "unique_strategies": 0,
                "overall_success_rate": 0.0,
                "top_strategies": [],
            }

        error_types = set()
        strategies: Dict[str, List[int]] = {}  # {strategy: [total, successes]}
        total_success = 0

        for row in rows:
            et = row.get("error_type", "").strip()
            strat = row.get("fix_strategy", "").strip()
            outcome = row.get("outcome", "")

            if et:
                error_types.add(et)
            if strat:
                if strat not in strategies:
                    strategies[strat] = [0, 0]
                strategies[strat][0] += 1
                if outcome == OUTCOME_SUCCESS:
                    strategies[strat][1] += 1
                    total_success += 1

        overall_rate = total_success / len(rows) if rows else 0.0

        # Build top strategies list
        ranked = sorted(
            [
                {
                    "strategy": s,
                    "total": v[0],
                    "successes": v[1],
                    "success_rate": round(v[1] / v[0], 3) if v[0] > 0 else 0.0,
                }
                for s, v in strategies.items()
            ],
            key=lambda x: (-float(x["success_rate"]), -int(x["total"])),  # type: ignore[operator]
        )

        return {
            "total_rows": len(rows),
            "unique_errors": len(error_types),
            "unique_strategies": len(strategies),
            "overall_success_rate": round(overall_rate, 3),
            "top_strategies": ranked[:5],
        }

    except Exception:
        return {
            "total_rows": 0,
            "unique_errors": 0,
            "unique_strategies": 0,
            "overall_success_rate": 0.0,
            "top_strategies": [],
        }


# ── Module smoke test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import tempfile

    print("experience_archive smoke test")
    errors: List[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        if condition:
            print(f"  PASS  {name}")
        else:
            msg = f"  FAIL  {name}"
            if detail:
                msg += f" — {detail}"
            print(msg)
            errors.append(name)

    # Redirect ARCHIVE_PATH to a temp file for the test
    import hooks.shared.experience_archive as _ea  # type: ignore

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as _tmp:
        _tmp_path = _tmp.name

    original_path = _ea.ARCHIVE_PATH
    _ea.ARCHIVE_PATH = _tmp_path

    try:
        # record_fix — success
        ok = _ea.record_fix("ImportError", "add-missing-import", "success", "/tmp/foo.py", "gate_15", 1.2)
        check("record_fix returns True", ok, f"got {ok}")

        # record_fix — failure
        _ea.record_fix("ImportError", "add-missing-import", "failure", "/tmp/foo.py", "gate_15", 0.5)
        _ea.record_fix("ImportError", "reinstall-package", "success", "/tmp/foo.py", "", 3.1)
        _ea.record_fix("SyntaxError", "rewrite-block", "success", "/tmp/bar.py", "gate_1", 0.8)
        _ea.record_fix("SyntaxError", "rewrite-block", "success", "/tmp/bar.py", "gate_1", 0.9)
        _ea.record_fix("SyntaxError", "rewrite-block", "failure", "/tmp/bar.py", "gate_1", 1.1)

        # query_best_strategy
        best = _ea.query_best_strategy("ImportError")
        # Both "add-missing-import" (1/2=0.5) and "reinstall-package" (1/1=1.0)
        check("query_best_strategy ImportError", best == "reinstall-package", f"got '{best}'")

        best_syntax = _ea.query_best_strategy("SyntaxError")
        check("query_best_strategy SyntaxError", best_syntax == "rewrite-block", f"got '{best_syntax}'")

        best_none = _ea.query_best_strategy("NonExistentError")
        check("query_best_strategy unknown returns ''", best_none == "", f"got '{best_none}'")

        # get_success_rate
        rate_add = _ea.get_success_rate("add-missing-import")
        check("get_success_rate 0.5", abs(rate_add - 0.5) < 0.001, f"got {rate_add}")

        rate_reinstall = _ea.get_success_rate("reinstall-package")
        check("get_success_rate 1.0", abs(rate_reinstall - 1.0) < 0.001, f"got {rate_reinstall}")

        rate_missing = _ea.get_success_rate("nonexistent-strategy")
        check("get_success_rate missing returns 0.0", rate_missing == 0.0, f"got {rate_missing}")

        rate_rewrite = _ea.get_success_rate("rewrite-block")
        check("get_success_rate 2/3", abs(rate_rewrite - 2 / 3) < 0.001, f"got {rate_rewrite}")

        # get_archive_stats
        stats = _ea.get_archive_stats()
        check("stats total_rows == 6", stats["total_rows"] == 6, f"got {stats['total_rows']}")
        check("stats unique_errors == 2", stats["unique_errors"] == 2, f"got {stats['unique_errors']}")
        check("stats unique_strategies == 3", stats["unique_strategies"] == 3, f"got {stats['unique_strategies']}")
        check("stats overall_success_rate > 0", stats["overall_success_rate"] > 0)
        check("stats top_strategies non-empty", len(stats["top_strategies"]) > 0)

        # Invalid outcome is coerced to "failure"
        _ea.record_fix("TypeError", "bad-strategy", "weird_outcome")
        rows_after = _ea._read_rows(_ea.ARCHIVE_PATH)
        last_row = rows_after[-1]
        check("invalid outcome coerced to failure", last_row["outcome"] == "failure",
              f"got '{last_row['outcome']}'")

        # Empty archive (use separate temp file)
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as _empty:
            _empty_path = _empty.name
        _ea.ARCHIVE_PATH = _empty_path
        check("query_best_strategy empty returns ''", _ea.query_best_strategy("anything") == "")
        check("get_success_rate empty returns 0.0", _ea.get_success_rate("s") == 0.0)
        empty_stats = _ea.get_archive_stats()
        check("stats empty total_rows == 0", empty_stats["total_rows"] == 0)
        os.remove(_empty_path)

    finally:
        _ea.ARCHIVE_PATH = original_path
        try:
            os.remove(_tmp_path)
        except OSError:
            pass

    print()
    if errors:
        print(f"FAILED: {len(errors)} test(s) failed: {errors}")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")
        sys.exit(0)
