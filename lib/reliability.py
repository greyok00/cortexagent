#!/usr/bin/env python3
"""reliability — retry decorator + circuit breaker (stdlib-only).

Minimal retry decorator + circuit breaker. No external DB or event log.

  @retry(max_retries=3, base_delay=1.0, exceptions=(...,))
        Exponential backoff with jitter. Re-raises after exhausting retries.

  CircuitBreaker(name, threshold=5, cooldown_seconds=60)
        After N consecutive failures the breaker opens; subsequent calls
        raise CircuitBreakerOpenError until cooldown elapses, then half-open
        to test recovery.

Env knobs (all optional):
  CORTEXAGENT_RETRY_MAX       default 3
  CORTEXAGENT_RETRY_DELAY     default 1.0 (seconds base)
  CORTEXAGENT_CB_THRESHOLD    default 5
  CORTEXAGENT_CB_COOLDOWN     default 60 (seconds)

Stdlib only. The model calls these via Bash scripts it writes, or any helper
it imports from lib/.
"""
from __future__ import annotations

import os
import random
import sys
import time
from dataclasses import dataclass, field
from functools import wraps
from typing import Callable, Iterable, Optional, Tuple, Type, Any


class CircuitBreakerOpenError(Exception):
    """Raised when a call hits an open circuit breaker."""


# ── Defaults from env ──────────────────────────────────────────────────────
def _retry_max() -> int:
    try:
        return int(os.environ.get("CORTEXAGENT_RETRY_MAX", "3"))
    except ValueError:
        return 3


def _retry_delay() -> float:
    try:
        return float(os.environ.get("CORTEXAGENT_RETRY_DELAY", "1.0"))
    except ValueError:
        return 1.0


def _cb_threshold() -> int:
    try:
        return int(os.environ.get("CORTEXAGENT_CB_THRESHOLD", "5"))
    except ValueError:
        return 5


def _cb_cooldown() -> float:
    try:
        return float(os.environ.get("CORTEXAGENT_CB_COOLDOWN", "60"))
    except ValueError:
        return 60.0


# ── retry decorator ────────────────────────────────────────────────────────
def retry(
    max_retries: Optional[int] = None,
    base_delay: Optional[float] = None,
    exceptions: Tuple[Type[BaseException], ...] = (Exception,),
    on_retry: Optional[Callable[[int, BaseException, float], None]] = None,
) -> Callable:
    """Retry decorator with exponential backoff + jitter.

    Args:
      max_retries: total attempts INCLUDING the first (default from env).
      base_delay:  initial backoff in seconds; doubles each attempt up to 30s.
      exceptions:  tuple of exception types that trigger a retry.
      on_retry:    optional callback(attempt, error, delay) fired before each sleep.
    """
    mr = max_retries if max_retries is not None else _retry_max()
    bd = base_delay if base_delay is not None else _retry_delay()

    def deco(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapped(*args, **kwargs):
            attempt = 0
            last_exc: Optional[BaseException] = None
            while attempt < mr:
                try:
                    return fn(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    attempt += 1
                    if attempt >= mr:
                        break
                    delay = min(bd * (2 ** (attempt - 1)), 30.0)
                    delay += random.uniform(0, delay * 0.25)  # jitter
                    if on_retry:
                        try:
                            on_retry(attempt, e, delay)
                        except Exception:
                            pass
                    time.sleep(delay)
            assert last_exc is not None
            raise last_exc
        return wrapped
    return deco


# ── CircuitBreaker ─────────────────────────────────────────────────────────
@dataclass
class CircuitBreaker:
    name: str
    threshold: int = field(default_factory=_cb_threshold)
    cooldown_seconds: float = field(default_factory=_cb_cooldown)
    _consecutive_failures: int = 0
    _opened_at: Optional[float] = None

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self.cooldown_seconds:
            # half-open: allow one probe
            return False
        return True

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.threshold and self._opened_at is None:
            self._opened_at = time.monotonic()

    def __enter__(self) -> "CircuitBreaker":
        if self.is_open:
            raise CircuitBreakerOpenError(
                f"circuit '{self.name}' is OPEN — "
                f"{self._consecutive_failures} consecutive failures, "
                f"cooldown {self.cooldown_seconds}s"
            )
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self.record_success()
        else:
            self.record_failure()
        return False  # don't suppress


# Module-level registry so multiple breakers across the process can be
# referenced by name.
_REGISTRY: dict = {}


def get_circuit_breaker(name: str, threshold: Optional[int] = None,
                        cooldown_seconds: Optional[float] = None) -> CircuitBreaker:
    cb = _REGISTRY.get(name)
    if cb is None:
        cb = CircuitBreaker(
            name=name,
            threshold=threshold if threshold is not None else _cb_threshold(),
            cooldown_seconds=cooldown_seconds if cooldown_seconds is not None else _cb_cooldown(),
        )
        _REGISTRY[name] = cb
    return cb


# ── CLI / smoke ────────────────────────────────────────────────────────────
def _smoke() -> int:
    """Quick self-test: succeeds, fails, retries, breaker opens."""
    print("reliability: smoke test")

    # retry — success after 2 fails
    calls = {"n": 0}

    @retry(max_retries=4, base_delay=0.05)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError(f"transient {calls['n']}")
        return "ok"

    print(f"  retry result: {flaky()} after {calls['n']} calls")
    assert calls["n"] == 3

    # retry — exhausts and re-raises
    calls2 = {"n": 0}

    @retry(max_retries=2, base_delay=0.01)
    def always_fail():
        calls2["n"] += 1
        raise RuntimeError("nope")

    try:
        always_fail()
    except RuntimeError as e:
        print(f"  retry exhausted: re-raised {type(e).__name__} after {calls2['n']} calls")
    assert calls2["n"] == 2

    # breaker
    cb = CircuitBreaker(name="smoke", threshold=2, cooldown_seconds=0.5)
    print(f"  breaker initial open? {cb.is_open}")
    try:
        with cb:
            raise ValueError("x")
    except ValueError:
        pass
    try:
        with cb:
            raise ValueError("x")
    except ValueError:
        pass
    print(f"  breaker open after 2 failures? {cb.is_open}")
    assert cb.is_open
    time.sleep(0.55)
    print(f"  breaker half-open after cooldown? open={cb.is_open}")
    assert not cb.is_open
    with cb:
        pass
    print(f"  breaker closed after success? open={cb.is_open}")
    assert not cb.is_open

    print("reliability: OK")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":
        sys.exit(_smoke())
    print("usage: reliability.py smoke", file=sys.stderr)
    sys.exit(2)