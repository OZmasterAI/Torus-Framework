#!/usr/bin/env python3
"""Benchmark: tmpfs vs disk I/O for audit-style JSONL writes.

Measures 1000 append operations to both tmpfs and disk paths under two modes:
  1. Buffered (default) — OS page cache absorbs disk writes
  2. Durable (fsync) — forces data to backing store

Reports p50/p95/p99 latencies and speedup factor.
"""

import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ITERATIONS = 1000
TMPFS_DIR = "/run/user/$UID/claude-hooks"
DISK_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks")


def make_entry(i):
    """Create a realistic audit log entry."""
    return json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "gate": f"GATE {i % 12 + 1}: BENCHMARK",
        "tool": "Bash",
        "decision": "pass",
        "reason": f"Benchmark iteration {i}",
        "session_id": "bench-session",
        "state_keys": ["files_read", "pending_verification"],
        "severity": "info",
    }) + "\n"


def benchmark_writes(directory, fsync_each=False):
    """Run ITERATIONS append writes and return latency list in microseconds."""
    os.makedirs(directory, exist_ok=True)
    filepath = os.path.join(directory, "benchmark_test.jsonl")

    if os.path.exists(filepath):
        os.remove(filepath)

    latencies = []
    for i in range(ITERATIONS):
        entry = make_entry(i)
        t0 = time.perf_counter_ns()
        with open(filepath, "a") as f:
            f.write(entry)
            if fsync_each:
                f.flush()
                os.fsync(f.fileno())
        t1 = time.perf_counter_ns()
        latencies.append((t1 - t0) / 1000)

    os.remove(filepath)
    return latencies


def print_stats(label, latencies):
    """Print percentile stats for a latency list."""
    latencies_sorted = sorted(latencies)
    p50 = statistics.median(latencies)
    p95 = latencies_sorted[int(len(latencies_sorted) * 0.95)]
    p99 = latencies_sorted[int(len(latencies_sorted) * 0.99)]
    mean = statistics.mean(latencies)
    total_ms = sum(latencies) / 1000

    print(f"\n  {label} ({ITERATIONS} writes):")
    print(f"    Mean:  {mean:8.1f} us")
    print(f"    p50:   {p50:8.1f} us")
    print(f"    p95:   {p95:8.1f} us")
    print(f"    p99:   {p99:8.1f} us")
    print(f"    Total: {total_ms:8.1f} ms")
    return {"mean": mean, "p50": p50, "p95": p95, "p99": p99, "total_ms": total_ms}


def print_speedup(tmpfs_stats, disk_stats):
    """Print speedup factors between two stat sets."""
    print(f"\n  Speedup factors:")
    for metric in ["mean", "p50", "p95", "p99"]:
        if tmpfs_stats[metric] > 0:
            factor = disk_stats[metric] / tmpfs_stats[metric]
            print(f"    {metric:>4}: {factor:6.1f}x faster on tmpfs")
    total_factor = disk_stats["total_ms"] / tmpfs_stats["total_ms"] if tmpfs_stats["total_ms"] > 0 else 0
    print(f"\n  Total: tmpfs={tmpfs_stats['total_ms']:.1f}ms vs disk={disk_stats['total_ms']:.1f}ms ({total_factor:.1f}x)")


def main():
    print("=" * 60)
    print("  I/O Benchmark: tmpfs vs disk (JSONL audit writes)")
    print("=" * 60)

    if not os.path.isdir(TMPFS_DIR):
        print(f"\n  ERROR: tmpfs not available at {TMPFS_DIR}")
        sys.exit(1)

    bench_tmpfs_dir = os.path.join(TMPFS_DIR, "benchmark")
    bench_disk_dir = os.path.join(DISK_DIR, ".benchmark")

    # Warmup
    print("\n  Warming up...")
    for d in [bench_tmpfs_dir, bench_disk_dir]:
        os.makedirs(d, exist_ok=True)
        warmup_path = os.path.join(d, "warmup.tmp")
        for _ in range(3):
            with open(warmup_path, "a") as f:
                f.write("warmup\n")
        os.remove(warmup_path)

    # ── Test 1: Buffered writes (page cache) ──────────────────
    print("\n  [Test 1] Buffered writes (no fsync)...")
    print("  Running tmpfs...")
    tmpfs_buf = benchmark_writes(bench_tmpfs_dir, fsync_each=False)
    print("  Running disk...")
    disk_buf = benchmark_writes(bench_disk_dir, fsync_each=False)

    print("\n" + "-" * 60)
    print("  TEST 1: BUFFERED (page cache)")
    print("-" * 60)
    tmpfs_buf_s = print_stats("tmpfs (RAM)", tmpfs_buf)
    disk_buf_s = print_stats("disk (page cache)", disk_buf)
    print_speedup(tmpfs_buf_s, disk_buf_s)

    # ── Test 2: Durable writes (fsync) ────────────────────────
    print("\n\n  [Test 2] Durable writes (fsync each)...")
    print("  Running tmpfs...")
    tmpfs_sync = benchmark_writes(bench_tmpfs_dir, fsync_each=True)
    print("  Running disk...")
    disk_sync = benchmark_writes(bench_disk_dir, fsync_each=True)

    print("\n" + "-" * 60)
    print("  TEST 2: DURABLE (fsync)")
    print("-" * 60)
    tmpfs_sync_s = print_stats("tmpfs (RAM + fsync)", tmpfs_sync)
    disk_sync_s = print_stats("disk (fsync)", disk_sync)
    print_speedup(tmpfs_sync_s, disk_sync_s)

    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    buf_factor = disk_buf_s["mean"] / tmpfs_buf_s["mean"] if tmpfs_buf_s["mean"] > 0 else 0
    sync_factor = disk_sync_s["mean"] / tmpfs_sync_s["mean"] if tmpfs_sync_s["mean"] > 0 else 0
    print(f"  Buffered:  {buf_factor:.1f}x faster (page cache masks disk latency)")
    print(f"  Durable:   {sync_factor:.1f}x faster (true hardware gap)")
    print(f"\n  Note: Hook I/O uses buffered writes (no fsync).")
    print(f"  Tmpfs benefit is latency stability + zero disk contention.")
    print("=" * 60)

    # Cleanup
    try:
        os.rmdir(bench_tmpfs_dir)
        os.rmdir(bench_disk_dir)
    except OSError:
        pass


if __name__ == "__main__":
    main()
