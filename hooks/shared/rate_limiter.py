"""Token bucket rate limiter for the Torus framework.

Implements per-key token bucket rate limiting with configurable rate and burst.
State is persisted to /dev/shm/claude-hooks/rate_limiter.json for fast ramdisk
access. Falls back to in-memory-only on any I/O error (fail-open).

Token bucket algorithm:
  - Each key has a bucket with a capacity of `burst` tokens.
  - Tokens refill at `rate` tokens/minute continuously (not in discrete intervals).
  - A call consumes `tokens` from the bucket; if insufficient tokens remain, the
    call is denied.
  - Buckets start full.

Preset configurations:
  TOOL_RATE  — 10 calls/min, burst 10   (e.g. "tool:Edit", "tool:Bash")
  GATE_RATE  — 30 calls/min, burst 30   (e.g. "gate:gate_04")
  API_RATE   — 60 calls/min, burst 60   (e.g. "api:memory")

Usage::

    from shared.rate_limiter import allow, consume, get_remaining, reset, get_all_limits

    if allow("tool:Edit"):
        # proceed
        pass
"""

import json
import os
import sys
import time
from typing import Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Persistence path
# ---------------------------------------------------------------------------

RAMDISK_PATH = "/dev/shm/claude-hooks/rate_limiter.json"

# ---------------------------------------------------------------------------
# Preset configurations: (rate_per_minute, burst)
# ---------------------------------------------------------------------------

TOOL_RATE: Tuple[float, int] = (10.0, 10)
GATE_RATE: Tuple[float, int] = (30.0, 30)
API_RATE:  Tuple[float, int] = (60.0, 60)

# Mapping of key-prefix -> (rate_per_minute, burst)
# Keys are matched by prefix: "tool:" -> TOOL_RATE, "gate:" -> GATE_RATE, "api:" -> API_RATE
_PRESET_MAP: Dict[str, Tuple[float, int]] = {
    "tool:": TOOL_RATE,
    "gate:": GATE_RATE,
    "api:":  API_RATE,
}

# Default for keys that do not match any prefix
_DEFAULT_RATE: Tuple[float, int] = GATE_RATE

# ---------------------------------------------------------------------------
# Internal in-memory store
# Bucket state: key -> {"tokens": float, "last_refill": float (unix epoch)}
# ---------------------------------------------------------------------------

_buckets: Dict[str, dict] = {}

# ---------------------------------------------------------------------------
# Helper: resolve config for a key
# ---------------------------------------------------------------------------

def _config_for(key: str) -> Tuple[float, int]:
    """Return (rate_per_minute, burst) for the given key based on prefix."""
    for prefix, cfg in _PRESET_MAP.items():
        if key.startswith(prefix):
            return cfg
    return _DEFAULT_RATE


def _refill_tokens(bucket: dict, rate_per_minute: float, burst: int, now: float) -> float:
    """Compute refilled token count based on elapsed time.

    Args:
        bucket: Dict with "tokens" and "last_refill" keys.
        rate_per_minute: Tokens added per minute.
        burst: Maximum bucket capacity.
        now: Current unix timestamp.

    Returns:
        Updated token count (capped at burst).
    """
    elapsed = now - bucket["last_refill"]
    # Convert rate to tokens-per-second for the elapsed calculation
    refill = elapsed * (rate_per_minute / 60.0)
    return min(burst, bucket["tokens"] + refill)


def _get_or_create_bucket(key: str, now: float) -> dict:
    """Return the bucket for key, creating a full bucket if absent."""
    if key not in _buckets:
        rate, burst = _config_for(key)
        _buckets[key] = {
            "tokens": float(burst),
            "last_refill": now,
        }
    return _buckets[key]


# ---------------------------------------------------------------------------
# Persistence — fail-open (all errors silently ignored)
# ---------------------------------------------------------------------------

def _save() -> None:
    """Persist current bucket state to ramdisk. Fail-open."""
    try:
        os.makedirs(os.path.dirname(RAMDISK_PATH), exist_ok=True)
        # Write atomically via temp file
        tmp = RAMDISK_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(_buckets, f)
        os.replace(tmp, RAMDISK_PATH)
    except Exception:
        pass  # fail-open: persistence is best-effort


def _load() -> None:
    """Load bucket state from ramdisk into _buckets. Fail-open."""
    global _buckets
    try:
        if not os.path.exists(RAMDISK_PATH):
            return
        with open(RAMDISK_PATH) as f:
            data = json.load(f)
        if isinstance(data, dict):
            # Validate entries — skip malformed ones
            cleaned = {}
            for k, v in data.items():
                if (
                    isinstance(v, dict)
                    and "tokens" in v
                    and "last_refill" in v
                    and isinstance(v["tokens"], (int, float))
                    and isinstance(v["last_refill"], (int, float))
                ):
                    cleaned[k] = {"tokens": float(v["tokens"]), "last_refill": float(v["last_refill"])}
            _buckets.update(cleaned)
    except Exception:
        pass  # fail-open: corrupt or missing file is not fatal


# Load persisted state once at import time
_load()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def allow(key: str, tokens: int = 1) -> bool:
    """Check if `tokens` are available for `key` WITHOUT consuming them.

    Returns True if the bucket has enough tokens, False otherwise.
    Returns True on any internal error (fail-open).

    Args:
        key:    Rate limit key, e.g. "tool:Edit", "gate:gate_04", "api:memory".
        tokens: Number of tokens to check for (default 1).

    Returns:
        True if allowed, False if rate-limited.
    """
    try:
        now = time.time()
        rate, burst = _config_for(key)
        bucket = _get_or_create_bucket(key, now)
        current = _refill_tokens(bucket, rate, burst, now)
        return current >= tokens
    except Exception:
        return True  # fail-open


def consume(key: str, tokens: int = 1) -> bool:
    """Attempt to consume `tokens` from the bucket for `key`.

    Refills the bucket based on elapsed time, then deducts `tokens` if
    sufficient tokens are available.

    Returns True if tokens were successfully consumed (call allowed).
    Returns False if insufficient tokens (call rate-limited).
    Returns True on any internal error (fail-open).

    Args:
        key:    Rate limit key, e.g. "tool:Edit", "gate:gate_04", "api:memory".
        tokens: Number of tokens to consume (default 1).

    Returns:
        True if consumed (allowed), False if denied (rate-limited).
    """
    try:
        now = time.time()
        rate, burst = _config_for(key)
        bucket = _get_or_create_bucket(key, now)

        # Refill based on time elapsed since last call
        bucket["tokens"] = _refill_tokens(bucket, rate, burst, now)
        bucket["last_refill"] = now

        if bucket["tokens"] >= tokens:
            bucket["tokens"] -= tokens
            _save()
            return True
        else:
            _save()
            return False
    except Exception:
        return True  # fail-open


def get_remaining(key: str) -> int:
    """Return the number of whole tokens remaining in the bucket for `key`.

    Accounts for time-based refill since the last consume.
    Returns the burst capacity on any internal error (fail-open / most permissive).

    Args:
        key: Rate limit key, e.g. "tool:Edit".

    Returns:
        Integer token count remaining (0 to burst).
    """
    try:
        now = time.time()
        rate, burst = _config_for(key)
        bucket = _get_or_create_bucket(key, now)
        current = _refill_tokens(bucket, rate, burst, now)
        return int(current)
    except Exception:
        _, burst = _config_for(key)
        return burst  # fail-open: return max


def reset(key: str) -> None:
    """Reset the bucket for `key` to full capacity.

    If the key does not exist yet, this call creates a full bucket for it.
    Silently ignores any internal error (fail-open).

    Args:
        key: Rate limit key to reset.
    """
    try:
        now = time.time()
        _, burst = _config_for(key)
        _buckets[key] = {
            "tokens": float(burst),
            "last_refill": now,
        }
        _save()
    except Exception:
        pass  # fail-open


def get_all_limits() -> dict:
    """Return a snapshot of all current bucket states with their config.

    Each entry in the returned dict has the form::

        {
            "tokens_remaining": int,
            "rate_per_minute": float,
            "burst": int,
            "last_refill": float,   # unix timestamp
        }

    Reflects time-based refill as of the moment of the call.
    Returns an empty dict on any internal error (fail-open).

    Returns:
        Dict mapping key -> limit info dict.
    """
    try:
        now = time.time()
        result = {}
        for key, bucket in _buckets.items():
            rate, burst = _config_for(key)
            current = _refill_tokens(bucket, rate, burst, now)
            result[key] = {
                "tokens_remaining": int(current),
                "rate_per_minute": rate,
                "burst": burst,
                "last_refill": bucket["last_refill"],
            }
        return result
    except Exception:
        return {}  # fail-open


# ---------------------------------------------------------------------------
# Smoke test (run as __main__)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    PASS_COUNT = 0
    FAIL_COUNT = 0

    def assert_test(name: str, condition: bool, detail: str = "") -> None:
        global PASS_COUNT, FAIL_COUNT
        if condition:
            PASS_COUNT += 1
            print(f"  PASS  {name}")
        else:
            FAIL_COUNT += 1
            print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))

    # Use test-only keys to avoid polluting real limits
    TEST_KEY_TOOL = "tool:__smoke_test__"
    TEST_KEY_GATE = "gate:__smoke_test__"
    TEST_KEY_API  = "api:__smoke_test__"
    TEST_KEY_MISC = "custom:__smoke_test__"

    # Reset all test keys before starting
    reset(TEST_KEY_TOOL)
    reset(TEST_KEY_GATE)
    reset(TEST_KEY_API)
    reset(TEST_KEY_MISC)

    print("\n--- rate_limiter.py smoke test ---\n")

    # 1. Fresh bucket starts at full capacity
    remaining = get_remaining(TEST_KEY_TOOL)
    assert_test(
        "1. tool: key starts at burst capacity (10)",
        remaining == 10,
        f"got {remaining}",
    )

    # 2. allow() returns True when bucket is full
    assert_test(
        "2. allow() True when bucket full",
        allow(TEST_KEY_TOOL),
        "should be allowed",
    )

    # 3. consume() decrements the bucket
    ok = consume(TEST_KEY_TOOL)
    assert_test("3. consume() returns True (allowed)", ok, "should be True")
    remaining_after = get_remaining(TEST_KEY_TOOL)
    assert_test(
        "4. get_remaining() decremented by 1 after consume",
        remaining_after == 9,
        f"got {remaining_after}",
    )

    # 4. Exhaust the tool bucket
    for _ in range(9):
        consume(TEST_KEY_TOOL)
    empty_remaining = get_remaining(TEST_KEY_TOOL)
    assert_test(
        "5. Bucket empty after consuming all tokens",
        empty_remaining == 0,
        f"got {empty_remaining}",
    )

    # 5. consume() returns False on empty bucket
    denied = consume(TEST_KEY_TOOL)
    assert_test(
        "6. consume() returns False when bucket empty",
        denied is False,
        f"got {denied}",
    )

    # 6. allow() returns False on empty bucket
    allowed_empty = allow(TEST_KEY_TOOL)
    assert_test(
        "7. allow() returns False when bucket empty",
        allowed_empty is False,
        f"got {allowed_empty}",
    )

    # 7. reset() refills bucket to full
    reset(TEST_KEY_TOOL)
    after_reset = get_remaining(TEST_KEY_TOOL)
    assert_test(
        "8. reset() refills bucket to burst (10)",
        after_reset == 10,
        f"got {after_reset}",
    )

    # 8. gate: key uses GATE_RATE preset (burst=30)
    reset(TEST_KEY_GATE)
    gate_remaining = get_remaining(TEST_KEY_GATE)
    assert_test(
        "9. gate: key uses burst=30 (GATE_RATE)",
        gate_remaining == 30,
        f"got {gate_remaining}",
    )

    # 9. api: key uses API_RATE preset (burst=60)
    reset(TEST_KEY_API)
    api_remaining = get_remaining(TEST_KEY_API)
    assert_test(
        "10. api: key uses burst=60 (API_RATE)",
        api_remaining == 60,
        f"got {api_remaining}",
    )

    # 10. get_all_limits() returns dict with test keys
    limits = get_all_limits()
    assert_test(
        "11. get_all_limits() includes consumed tool key",
        TEST_KEY_TOOL in limits,
        f"keys: {list(limits.keys())}",
    )

    # 11. get_all_limits() entry has expected fields
    if TEST_KEY_TOOL in limits:
        entry = limits[TEST_KEY_TOOL]
        has_fields = all(k in entry for k in ("tokens_remaining", "rate_per_minute", "burst", "last_refill"))
        assert_test(
            "12. get_all_limits() entry has all required fields",
            has_fields,
            f"got keys: {list(entry.keys())}",
        )
    else:
        assert_test("12. get_all_limits() entry has all required fields", False, "key missing")

    # 12. Verify ramdisk file was written
    assert_test(
        "13. Ramdisk persistence file written to /dev/shm/claude-hooks/rate_limiter.json",
        os.path.exists(RAMDISK_PATH),
        f"file not found at {RAMDISK_PATH}",
    )

    # 13. Verify fail-open on bad key (no prefix match uses default config)
    reset(TEST_KEY_MISC)
    misc_remaining = get_remaining(TEST_KEY_MISC)
    rate, burst = _DEFAULT_RATE
    assert_test(
        f"14. Unknown prefix uses default config (burst={burst})",
        misc_remaining == burst,
        f"got {misc_remaining}",
    )

    # Summary
    print(f"\n{'='*40}")
    print(f"Results: {PASS_COUNT} passed, {FAIL_COUNT} failed")
    print(f"{'='*40}\n")

    if FAIL_COUNT > 0:
        sys.exit(1)
