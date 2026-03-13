"""Batch processor for framework operations.

Provides a reusable pattern for processing collections of items with:
- Configurable batch sizes
- Progress tracking and reporting
- Per-item error handling (fail-safe: errors don't stop the batch)
- Results aggregation with success/failure counts
- Optional dry-run mode

Typical usage::

    from shared.batch_processor import process_batch, BatchResult

    def process_one(item):
        # do work, return result or raise
        return item * 2

    result = process_batch(my_list, process_one, batch_size=50)
    print(result.to_dict())
"""

import time
from typing import Any, Callable, List, Optional


# ── Result container ─────────────────────────────────────────────────────────


class BatchResult:
    """Result of a batch processing run."""

    __slots__ = (
        "total",
        "succeeded",
        "failed",
        "skipped",
        "errors",
        "results",
        "duration_ms",
    )

    def __init__(self) -> None:
        self.total: int = 0
        self.succeeded: int = 0
        self.failed: int = 0
        self.skipped: int = 0
        self.errors: List[dict] = []
        self.results: List[Any] = []
        self.duration_ms: float = 0.0

    def to_dict(self) -> dict:
        """Return a JSON-serialisable summary of the batch run.

        Caps the inline error list at 20 entries to avoid bloated payloads;
        full error detail is always available via the ``errors`` attribute.
        """
        return {
            "total": self.total,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "skipped": self.skipped,
            "errors": self.errors[:20],  # cap error list
            "duration_ms": round(self.duration_ms, 2),
            "success_rate": round(self.succeeded / max(self.total, 1) * 100, 1),
        }

    def __repr__(self) -> str:
        return (
            f"BatchResult(total={self.total}, ok={self.succeeded}, "
            f"fail={self.failed}, skip={self.skipped})"
        )


# ── Core batch API ───────────────────────────────────────────────────────────


def process_batch(
    items: list,
    processor: Callable[[Any], Any],
    batch_size: int = 50,
    on_progress: Optional[Callable[[int, int, "BatchResult"], None]] = None,
    skip_if: Optional[Callable[[Any], bool]] = None,
    dry_run: bool = False,
    label: str = "batch",
) -> BatchResult:
    """Process a list of items in batches.

    Each item is processed individually by *processor*.  Exceptions are caught
    per-item and recorded in ``BatchResult.errors`` — they do NOT abort the
    batch (fail-safe).

    Args:
        items:       Items to process.
        processor:   Function applied to each item.  Receives the item, returns
                     a result value.  May raise; the exception is captured and
                     counted as a failure.
        batch_size:  Items per logical batch, used only for the *on_progress*
                     callback frequency.  Does not affect concurrency or
                     chunking of actual work.
        on_progress: Optional callback invoked after every *batch_size* items
                     and once at the end.  Signature:
                     ``on_progress(processed_count, total, result_so_far)``.
        skip_if:     Optional predicate.  If it returns ``True`` for an item,
                     that item is counted as *skipped* and not passed to
                     *processor*.
        dry_run:     If ``True``, items are counted but *processor* is never
                     called.  All items are marked *succeeded*.
        label:       Informational label for logging / reporting (not used
                     internally but surfaced in progress callbacks for callers
                     that want to display context).

    Returns:
        :class:`BatchResult` with aggregated outcome counts and per-item
        error details.
    """
    result = BatchResult()
    result.total = len(items)
    start = time.monotonic()

    for i, item in enumerate(items):
        # Skip check
        if skip_if is not None and skip_if(item):
            result.skipped += 1
            continue

        # Dry run — count as success without doing real work
        if dry_run:
            result.succeeded += 1
            continue

        # Process — fail-safe: capture exceptions
        try:
            output = processor(item)
            result.succeeded += 1
            result.results.append(output)
        except Exception as exc:
            result.failed += 1
            result.errors.append(
                {
                    "item": str(item)[:200],
                    "error": str(exc)[:200],
                    "index": i,
                }
            )

        # Progress callback at batch boundaries
        if on_progress is not None and (i + 1) % batch_size == 0:
            on_progress(i + 1, result.total, result)

    result.duration_ms = (time.monotonic() - start) * 1000

    # Final progress callback (always called, even if total is 0)
    if on_progress is not None:
        on_progress(result.total, result.total, result)

    return result


# ── Convenience helpers ──────────────────────────────────────────────────────


def map_batch(
    items: list,
    mapper: Callable[[Any], Any],
    batch_size: int = 100,
) -> list:
    """Apply *mapper* to every item and return the results list.

    Unlike :func:`process_batch`, this is **fail-fast**: the first exception
    propagates immediately and the remaining items are not processed.

    Args:
        items:      Items to transform.
        mapper:     Function applied to each item; must return the mapped value.
        batch_size: Logical chunk size (items are still processed one-by-one;
                    this controls internal iteration granularity).

    Returns:
        List of mapped results in the same order as *items*.
    """
    results: List[Any] = []
    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        results.extend(mapper(item) for item in batch)
    return results


def filter_batch(
    items: list,
    predicate: Callable[[Any], bool],
    batch_size: int = 100,
) -> list:
    """Return the subset of *items* for which *predicate* returns ``True``.

    Args:
        items:      Items to filter.
        predicate:  Function that returns ``True`` to keep an item.
        batch_size: Logical chunk size for internal iteration.

    Returns:
        Filtered list preserving original order.
    """
    results: List[Any] = []
    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        results.extend(item for item in batch if predicate(item))
    return results


# ── Smoke test / CLI entry point ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    PASS_COUNT = 0
    FAIL_COUNT = 0

    def _assert(name: str, condition: bool, detail: str = "") -> None:
        global PASS_COUNT, FAIL_COUNT
        if condition:
            PASS_COUNT += 1
            print(f"  PASS  {name}")
        else:
            FAIL_COUNT += 1
            print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))

    print("\n--- batch_processor.py smoke test ---\n")

    # 1. Basic success path
    r = process_batch([1, 2, 3], lambda x: x * 10)
    _assert("1. succeeded count matches items", r.succeeded == 3, str(r))
    _assert("2. results list populated", r.results == [10, 20, 30], str(r.results))
    _assert("3. no failures", r.failed == 0, str(r))

    # 2. Fail-safe: error does not abort the batch
    def _sometimes_fail(x: int) -> int:
        if x == 2:
            raise ValueError("boom")
        return x

    r2 = process_batch([1, 2, 3], _sometimes_fail)
    _assert("4. partial failure: 2 succeeded", r2.succeeded == 2, str(r2))
    _assert("5. partial failure: 1 failed", r2.failed == 1, str(r2))
    _assert(
        "6. error entry has expected keys",
        all(k in r2.errors[0] for k in ("item", "error", "index")),
        str(r2.errors),
    )

    # 3. skip_if
    r3 = process_batch([1, 2, 3, 4], lambda x: x, skip_if=lambda x: x % 2 == 0)
    _assert("7. skip_if skips even numbers", r3.skipped == 2, str(r3))
    _assert("8. skip_if: odd numbers succeed", r3.succeeded == 2, str(r3))

    # 4. dry_run
    called: List[Any] = []
    r4 = process_batch([1, 2, 3], lambda x: called.append(x), dry_run=True)
    _assert("9. dry_run: processor not called", called == [], str(called))
    _assert("10. dry_run: all counted as succeeded", r4.succeeded == 3, str(r4))

    # 5. on_progress callback
    progress_log: List[Any] = []

    def _on_progress(done: int, total: int, res: BatchResult) -> None:
        progress_log.append((done, total))

    r5 = process_batch(
        list(range(10)), lambda x: x, batch_size=3, on_progress=_on_progress
    )
    _assert(
        "11. on_progress called at batch boundaries + final",
        len(progress_log) >= 2,
        str(progress_log),
    )
    _assert(
        "12. final on_progress entry has total==total",
        progress_log[-1] == (10, 10),
        str(progress_log),
    )

    # 6. to_dict() keys
    d = r.to_dict()
    expected_keys = {
        "total",
        "succeeded",
        "failed",
        "skipped",
        "errors",
        "duration_ms",
        "success_rate",
    }
    _assert(
        "13. to_dict() has all expected keys",
        expected_keys.issubset(d.keys()),
        str(set(d.keys())),
    )

    # 7. success_rate calculation
    r6 = process_batch([1, 2, 3, 4], lambda x: x)
    _assert(
        "14. success_rate is 100.0 for all-success",
        r6.to_dict()["success_rate"] == 100.0,
    )

    # 8. map_batch
    mapped = map_batch([1, 2, 3], lambda x: x + 1)
    _assert("15. map_batch returns correct results", mapped == [2, 3, 4], str(mapped))

    # 9. map_batch fail-fast
    try:
        map_batch([1, 2, 3], lambda x: 1 // (x - 2))
        _assert("16. map_batch fail-fast raises", False, "no exception raised")
    except ZeroDivisionError:
        _assert("16. map_batch fail-fast raises", True)

    # 10. filter_batch
    filtered = filter_batch([1, 2, 3, 4, 5], lambda x: x > 3)
    _assert(
        "17. filter_batch returns correct subset", filtered == [4, 5], str(filtered)
    )

    # 11. Empty input
    r7 = process_batch([], lambda x: x)
    _assert(
        "18. empty input: total=0, succeeded=0",
        r7.total == 0 and r7.succeeded == 0,
        str(r7),
    )
    _assert("19. empty input: success_rate=0.0", r7.to_dict()["success_rate"] == 0.0)

    # 12. duration_ms is non-negative
    _assert(
        "20. duration_ms is non-negative float",
        r.duration_ms >= 0.0,
        str(r.duration_ms),
    )

    # 13. repr
    _assert(
        "21. __repr__ contains key fields",
        "BatchResult(" in repr(r) and "ok=" in repr(r),
        repr(r),
    )

    # Summary
    print(f"\n{'=' * 40}")
    print(f"Results: {PASS_COUNT} passed, {FAIL_COUNT} failed")
    print(f"{'=' * 40}\n")

    if FAIL_COUNT > 0:
        sys.exit(1)
