"""Configurable retry strategies for the Torus framework.

Provides exponential, linear, constant, and fibonacci backoff strategies with
optional jitter. Tracks per-operation attempt history and exposes a decorator /
context-manager for transparent retry logic.

Design constraints:
- Fail-open: all public functions swallow exceptions and return safe defaults.
- No external dependencies beyond the standard library.
- Thread-safe per-operation tracking via plain dicts (each hook is a separate
  process; dict operations are GIL-atomic in CPython).

Strategies
----------
EXPONENTIAL_BACKOFF  base * multiplier^attempt  (classic)
LINEAR_BACKOFF       base + step * attempt
CONSTANT             always base_delay
FIBONACCI            fib(attempt) * base_delay

Jitter modes
------------
FULL          random(0, computed_delay)
EQUAL         computed_delay/2 + random(0, computed_delay/2)
DECORRELATED  random(base_delay, prev_delay * 3)  (AWS decorrelated jitter)
"""

from __future__ import annotations

import functools
import math
import random
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class Strategy(str, Enum):
    EXPONENTIAL_BACKOFF = "exponential_backoff"
    LINEAR_BACKOFF      = "linear_backoff"
    CONSTANT            = "constant"
    FIBONACCI           = "fibonacci"


class Jitter(str, Enum):
    NONE         = "none"
    FULL         = "full"
    EQUAL        = "equal"
    DECORRELATED = "decorrelated"


# ---------------------------------------------------------------------------
# Internal state per operation
# ---------------------------------------------------------------------------

@dataclass
class _OperationState:
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    last_delay: float = 0.0
    errors: List[str] = field(default_factory=list)   # last N error messages
    total_delay: float = 0.0                           # cumulative sleep time
    max_errors_stored: int = 10


# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------

@dataclass
class RetryConfig:
    strategy:    Strategy = Strategy.EXPONENTIAL_BACKOFF
    jitter:      Jitter   = Jitter.NONE
    max_retries: int      = 3
    base_delay:  float    = 1.0      # seconds
    max_delay:   float    = 60.0     # cap computed delay
    multiplier:  float    = 2.0      # for EXPONENTIAL_BACKOFF
    step:        float    = 1.0      # for LINEAR_BACKOFF


# ---------------------------------------------------------------------------
# Module-level registry: operation name -> _OperationState
# ---------------------------------------------------------------------------

_registry: Dict[str, _OperationState] = {}

# Default config used when callers don't supply one
_default_config = RetryConfig()


def _get_state(operation: str) -> _OperationState:
    """Return (creating if needed) the state for *operation*."""
    if operation not in _registry:
        _registry[operation] = _OperationState()
    return _registry[operation]


# ---------------------------------------------------------------------------
# Fibonacci cache (memoised to avoid O(n) recalculation on every call)
# ---------------------------------------------------------------------------

_fib_cache: Dict[int, int] = {0: 0, 1: 1}


def _fib(n: int) -> int:
    """Return the nth Fibonacci number (0-indexed)."""
    if n in _fib_cache:
        return _fib_cache[n]
    result = _fib(n - 1) + _fib(n - 2)
    _fib_cache[n] = result
    return result


# ---------------------------------------------------------------------------
# Delay computation (pure, no side-effects)
# ---------------------------------------------------------------------------

def _compute_raw_delay(attempt: int, config: RetryConfig) -> float:
    """Compute the delay for *attempt* (0-based) before jitter."""
    try:
        if config.strategy == Strategy.EXPONENTIAL_BACKOFF:
            raw = config.base_delay * (config.multiplier ** attempt)
        elif config.strategy == Strategy.LINEAR_BACKOFF:
            raw = config.base_delay + config.step * attempt
        elif config.strategy == Strategy.CONSTANT:
            raw = config.base_delay
        elif config.strategy == Strategy.FIBONACCI:
            fib_val = _fib(max(1, attempt + 1))  # fib(1)=1, fib(2)=1, fib(3)=2 …
            raw = config.base_delay * fib_val
        else:
            raw = config.base_delay
        return min(float(raw), config.max_delay)
    except Exception:
        return config.base_delay


def _apply_jitter(raw: float, config: RetryConfig, prev_delay: float) -> float:
    """Apply jitter to *raw* delay and return the final value."""
    try:
        if config.jitter == Jitter.NONE:
            return raw
        elif config.jitter == Jitter.FULL:
            return random.uniform(0.0, raw)
        elif config.jitter == Jitter.EQUAL:
            half = raw / 2.0
            return half + random.uniform(0.0, half)
        elif config.jitter == Jitter.DECORRELATED:
            low = config.base_delay
            high = max(low * 3.0, prev_delay * 3.0)
            return random.uniform(low, high)
        else:
            return raw
    except Exception:
        return raw


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def should_retry(operation: str, error: Any = None,
                 config: Optional[RetryConfig] = None) -> bool:
    """Return True if *operation* should be retried after the given error.

    Bases the decision purely on whether the failure count is still below
    max_retries.  Never raises.
    """
    try:
        cfg = config or _default_config
        state = _get_state(operation)
        return state.failures < cfg.max_retries
    except Exception:
        return False


def get_delay(operation: str, config: Optional[RetryConfig] = None) -> float:
    """Return the recommended delay (seconds) before the next retry.

    Uses the current failure count to determine the attempt number.
    Does NOT sleep — caller is responsible for sleeping.  Never raises.
    """
    try:
        cfg = config or _default_config
        state = _get_state(operation)
        attempt = max(0, state.failures)          # 0-based attempt index
        raw = _compute_raw_delay(attempt, cfg)
        delay = _apply_jitter(raw, cfg, state.last_delay)
        delay = max(0.0, min(delay, cfg.max_delay))
        return delay
    except Exception:
        return 0.0


def record_attempt(operation: str, success: bool,
                   error: Any = None,
                   config: Optional[RetryConfig] = None) -> None:
    """Record the outcome of one attempt for *operation*.

    Updates internal counters and stores the error message (if any) for
    diagnostics.  Never raises.
    """
    try:
        cfg = config or _default_config
        state = _get_state(operation)
        state.attempts += 1
        if success:
            state.successes += 1
        else:
            state.failures += 1
            if error is not None:
                msg = str(error)[:200]
                state.errors.append(msg)
                if len(state.errors) > state.max_errors_stored:
                    state.errors = state.errors[-state.max_errors_stored:]
        # Pre-compute and cache the delay for the NEXT attempt so get_delay()
        # can return it without re-running jitter (consistent per call cycle).
        raw = _compute_raw_delay(max(0, state.failures), cfg)
        delay = _apply_jitter(raw, cfg, state.last_delay)
        delay = max(0.0, min(delay, cfg.max_delay))
        state.last_delay = delay
        state.total_delay += delay
    except Exception:
        pass


def reset(operation: str) -> None:
    """Reset all tracking state for *operation*.  Never raises."""
    try:
        _registry[operation] = _OperationState()
    except Exception:
        pass


def get_stats(operation: str) -> Dict[str, Any]:
    """Return a stats snapshot for *operation*.

    Returns a plain dict with keys:
      attempts, successes, failures, last_delay, total_delay,
      recent_errors, success_rate

    Never raises — returns an empty dict on error.
    """
    try:
        state = _get_state(operation)
        success_rate = (
            state.successes / state.attempts if state.attempts > 0 else 0.0
        )
        return {
            "operation":    operation,
            "attempts":     state.attempts,
            "successes":    state.successes,
            "failures":     state.failures,
            "last_delay":   state.last_delay,
            "total_delay":  state.total_delay,
            "recent_errors": list(state.errors),
            "success_rate": round(success_rate, 4),
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# with_retry — decorator AND context-manager
# ---------------------------------------------------------------------------

class _RetryContextManager:
    """Returned by with_retry(); usable as both decorator and context manager.

    As a **decorator**::

        @with_retry(strategy=Strategy.EXPONENTIAL_BACKOFF, max_retries=3)
        def call_api():
            ...

    As a **context manager**::

        with with_retry("op", strategy=Strategy.LINEAR_BACKOFF) as rt:
            result = do_work()
            rt.success()          # mark success explicitly

    Never raises internally.
    """

    def __init__(self, func_or_operation: Any, config: RetryConfig):
        self._func: Optional[Callable] = None
        self._operation: str = ""
        self._config = config
        self._success_called = False

        if callable(func_or_operation):
            self._func = func_or_operation
            self._operation = getattr(func_or_operation, "__name__", "unknown")
        else:
            self._operation = str(func_or_operation) if func_or_operation else "unknown"

    # -- decorator behaviour --------------------------------------------------

    def __call__(self, *args, **kwargs):
        """When used as a decorator, wrap the underlying function with retry logic."""
        try:
            if self._func is None:
                # Called as with_retry("name", ...)(func) — return a new wrapper
                func = args[0] if args else None
                if callable(func):
                    return _RetryContextManager(func, self._config)
                return self

            op = self._operation
            last_exc = None
            while True:
                try:
                    result = self._func(*args, **kwargs)
                    record_attempt(op, success=True, config=self._config)
                    return result
                except Exception as exc:
                    last_exc = exc
                    record_attempt(op, success=False, error=exc, config=self._config)
                    if not should_retry(op, exc, config=self._config):
                        break
                    delay = get_delay(op, config=self._config)
                    if delay > 0:
                        time.sleep(delay)
            # Exhausted retries — re-raise last exception
            if last_exc is not None:
                raise last_exc
        except Exception:
            raise   # Let caller see function exceptions; only swallow internal errors

    # -- context manager behaviour --------------------------------------------

    def __enter__(self):
        self._success_called = False
        return self

    def success(self):
        """Mark the current attempt as successful (context-manager mode)."""
        try:
            record_attempt(self._operation, success=True, config=self._config)
            self._success_called = True
        except Exception:
            pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is not None:
                record_attempt(self._operation, success=False,
                               error=exc_val, config=self._config)
            elif not self._success_called:
                record_attempt(self._operation, success=True, config=self._config)
        except Exception:
            pass
        return False  # Never suppress exceptions


def with_retry(
    func_or_operation: Any = None,
    strategy:    Strategy = Strategy.EXPONENTIAL_BACKOFF,
    jitter:      Jitter   = Jitter.NONE,
    max_retries: int      = 3,
    base_delay:  float    = 1.0,
    max_delay:   float    = 60.0,
    multiplier:  float    = 2.0,
    step:        float    = 1.0,
    config:      Optional[RetryConfig] = None,
) -> _RetryContextManager:
    """Return a retry wrapper usable as a decorator or context manager.

    Parameters
    ----------
    func_or_operation:
        Either a callable (decorator usage) or an operation-name string
        (context-manager usage).  Can be omitted.
    strategy, jitter, max_retries, base_delay, max_delay, multiplier, step:
        Config knobs; ignored if *config* is supplied explicitly.
    config:
        Pre-built RetryConfig; overrides all individual knobs.

    Examples
    --------
    Decorator::

        @with_retry(strategy=Strategy.LINEAR_BACKOFF, max_retries=5)
        def unreliable_call():
            ...

    Context manager::

        with with_retry("fetch-data", strategy=Strategy.FIBONACCI) as rt:
            data = fetch()
            rt.success()
    """
    try:
        cfg = config or RetryConfig(
            strategy=strategy,
            jitter=jitter,
            max_retries=max_retries,
            base_delay=base_delay,
            max_delay=max_delay,
            multiplier=multiplier,
            step=step,
        )
        return _RetryContextManager(func_or_operation, cfg)
    except Exception:
        # Absolute last resort: return a no-op wrapper
        return _RetryContextManager(func_or_operation, RetryConfig())


# ---------------------------------------------------------------------------
# Smoke test (python -m shared.retry_strategy  OR  python retry_strategy.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    PASS = 0
    FAIL = 0

    def check(name: str, condition: bool, detail: str = "") -> None:
        global PASS, FAIL
        if condition:
            PASS += 1
            print(f"  PASS  {name}")
        else:
            FAIL += 1
            print(f"  FAIL  {name}" + (f" -- {detail}" if detail else ""))

    print("retry_strategy smoke tests")
    print("-" * 50)

    # --- 1. Fibonacci sequence correctness ------------------------------------
    check("fib(0)==0",  _fib(0) == 0)
    check("fib(1)==1",  _fib(1) == 1)
    check("fib(6)==8",  _fib(6) == 8)

    # --- 2. should_retry respects max_retries ---------------------------------
    reset("op_retry_limit")
    cfg3 = RetryConfig(max_retries=3)
    check("should_retry before any failure",
          should_retry("op_retry_limit", config=cfg3))
    for _ in range(3):
        record_attempt("op_retry_limit", success=False, config=cfg3)
    check("should_retry exhausted after 3 failures",
          not should_retry("op_retry_limit", config=cfg3))

    # --- 3. get_delay: CONSTANT strategy always returns base_delay ------------
    reset("op_constant")
    cfg_const = RetryConfig(strategy=Strategy.CONSTANT, base_delay=2.5,
                            jitter=Jitter.NONE)
    for i in range(4):
        delay = get_delay("op_constant", config=cfg_const)
        check(f"constant delay attempt {i} == 2.5",
              abs(delay - 2.5) < 1e-9, f"got {delay}")
        record_attempt("op_constant", success=False, config=cfg_const)

    # --- 4. get_delay: EXPONENTIAL_BACKOFF doubles each attempt ---------------
    reset("op_exp")
    cfg_exp = RetryConfig(strategy=Strategy.EXPONENTIAL_BACKOFF,
                          base_delay=1.0, multiplier=2.0, max_delay=100.0,
                          jitter=Jitter.NONE)
    delays_exp = []
    for i in range(4):
        delays_exp.append(get_delay("op_exp", config=cfg_exp))
        record_attempt("op_exp", success=False, config=cfg_exp)
    check("exponential delay sequence [1,2,4,8]",
          delays_exp == [1.0, 2.0, 4.0, 8.0],
          f"got {delays_exp}")

    # --- 5. get_delay: LINEAR_BACKOFF increases by step -----------------------
    reset("op_linear")
    cfg_lin = RetryConfig(strategy=Strategy.LINEAR_BACKOFF,
                          base_delay=1.0, step=2.0, max_delay=100.0,
                          jitter=Jitter.NONE)
    delays_lin = []
    for i in range(4):
        delays_lin.append(get_delay("op_linear", config=cfg_lin))
        record_attempt("op_linear", success=False, config=cfg_lin)
    check("linear delay sequence [1,3,5,7]",
          delays_lin == [1.0, 3.0, 5.0, 7.0],
          f"got {delays_lin}")

    # --- 6. get_delay: FIBONACCI strategy -------------------------------------
    reset("op_fib")
    cfg_fib = RetryConfig(strategy=Strategy.FIBONACCI, base_delay=1.0,
                          max_delay=100.0, jitter=Jitter.NONE)
    delays_fib = []
    for i in range(4):
        delays_fib.append(get_delay("op_fib", config=cfg_fib))
        record_attempt("op_fib", success=False, config=cfg_fib)
    # fib(1)=1, fib(2)=1, fib(3)=2, fib(4)=3  multiplied by base_delay=1
    check("fibonacci delay sequence [1,1,2,3]",
          delays_fib == [1.0, 1.0, 2.0, 3.0],
          f"got {delays_fib}")

    # --- 7. get_delay: max_delay cap ------------------------------------------
    reset("op_cap")
    cfg_cap = RetryConfig(strategy=Strategy.EXPONENTIAL_BACKOFF,
                          base_delay=1.0, multiplier=10.0, max_delay=5.0,
                          jitter=Jitter.NONE)
    for _ in range(10):
        record_attempt("op_cap", success=False, config=cfg_cap)
    d = get_delay("op_cap", config=cfg_cap)
    check("max_delay cap enforced",
          d <= 5.0 + 1e-9, f"got {d}")

    # --- 8. FULL jitter is within [0, raw_delay] ------------------------------
    reset("op_full_jitter")
    cfg_jit = RetryConfig(strategy=Strategy.CONSTANT, base_delay=4.0,
                          jitter=Jitter.FULL)
    jitter_results = [get_delay("op_full_jitter", config=cfg_jit) for _ in range(50)]
    check("full jitter always in [0, 4.0]",
          all(0.0 <= d <= 4.0 + 1e-9 for d in jitter_results),
          f"out-of-range: {[d for d in jitter_results if d > 4.0]}")

    # --- 9. EQUAL jitter is within [half, raw_delay] --------------------------
    reset("op_equal_jitter")
    cfg_eq = RetryConfig(strategy=Strategy.CONSTANT, base_delay=4.0,
                         jitter=Jitter.EQUAL)
    eq_results = [get_delay("op_equal_jitter", config=cfg_eq) for _ in range(50)]
    check("equal jitter always in [2.0, 4.0]",
          all(2.0 - 1e-9 <= d <= 4.0 + 1e-9 for d in eq_results),
          f"out-of-range: {[d for d in eq_results if d < 2.0 or d > 4.0]}")

    # --- 10. get_stats returns correct counters --------------------------------
    reset("op_stats")
    cfg_stats = RetryConfig(max_retries=10)
    record_attempt("op_stats", success=True,  config=cfg_stats)
    record_attempt("op_stats", success=False, error="boom", config=cfg_stats)
    record_attempt("op_stats", success=True,  config=cfg_stats)
    stats = get_stats("op_stats")
    check("get_stats attempts==3",   stats.get("attempts") == 3)
    check("get_stats successes==2",  stats.get("successes") == 2)
    check("get_stats failures==1",   stats.get("failures") == 1)
    check("get_stats recent_errors contains 'boom'",
          "boom" in stats.get("recent_errors", []))
    check("get_stats success_rate==0.6667",
          abs(stats.get("success_rate", 0) - 0.6667) < 0.001,
          f"got {stats.get('success_rate')}")

    # --- 11. reset clears state -----------------------------------------------
    reset("op_reset")
    record_attempt("op_reset", success=False)
    reset("op_reset")
    stats_after = get_stats("op_reset")
    check("reset clears attempts to 0", stats_after.get("attempts") == 0)

    # --- 12. with_retry as decorator ------------------------------------------
    call_count = {"n": 0}

    @with_retry(strategy=Strategy.CONSTANT, base_delay=0.0, max_retries=3)
    def flaky():
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise ValueError("not yet")
        return "ok"

    reset(flaky._operation)   # ensure clean state
    try:
        result = flaky()
        check("with_retry decorator: succeeds on 3rd attempt",
              result == "ok" and call_count["n"] == 3,
              f"result={result}, calls={call_count['n']}")
    except Exception as exc:
        check("with_retry decorator: succeeds on 3rd attempt",
              False, f"raised {exc}")

    # --- 13. with_retry as context manager ------------------------------------
    reset("op_ctx")
    with with_retry("op_ctx", strategy=Strategy.CONSTANT, base_delay=0.0) as rt:
        rt.success()
    ctx_stats = get_stats("op_ctx")
    check("with_retry context manager records success",
          ctx_stats.get("successes") == 1)

    # --- 14. fail-open: bad operation name doesn't raise ----------------------
    try:
        should_retry(None)           # type: ignore
        get_delay(None)              # type: ignore
        record_attempt(None, True)   # type: ignore
        reset(None)                  # type: ignore
        get_stats(None)              # type: ignore
        check("fail-open: None operation name is safe", True)
    except Exception as exc:
        check("fail-open: None operation name is safe", False, str(exc))

    # --- 15. DECORRELATED jitter is positive and above base_delay -------------
    reset("op_decorr")
    cfg_decorr = RetryConfig(strategy=Strategy.CONSTANT, base_delay=1.0,
                             jitter=Jitter.DECORRELATED)
    decorr_results = [get_delay("op_decorr", config=cfg_decorr) for _ in range(30)]
    check("decorrelated jitter >= base_delay",
          all(d >= 1.0 - 1e-9 for d in decorr_results),
          f"min={min(decorr_results):.4f}")

    # Summary
    print("-" * 50)
    total = PASS + FAIL
    print(f"Results: {PASS}/{total} passed" +
          (f", {FAIL} FAILED" if FAIL else ""))
    sys.exit(0 if FAIL == 0 else 1)
