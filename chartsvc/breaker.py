"""Minimal circuit breaker: closed -> open after N failures -> half-open trial."""

from __future__ import annotations

import threading
import time
from typing import Callable


class CircuitOpen(Exception):
    def __init__(self, retry_after: float):
        super().__init__("circuit open")
        self.retry_after = retry_after


class CircuitBreaker:
    def __init__(self, failure_threshold: int, reset_seconds: float,
                 clock: Callable[[], float] = time.monotonic):
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at = 0.0
        self._trial_in_flight = False

    @property
    def state(self) -> str:
        with self._lock:
            return self._state_locked()

    def _state_locked(self) -> str:
        if self._failures < self.failure_threshold:
            return "closed"
        if self._clock() - self._opened_at >= self.reset_seconds:
            return "half-open"
        return "open"

    def before_call(self) -> None:
        """Raise :class:`CircuitOpen` unless a call may go through now."""
        with self._lock:
            state = self._state_locked()
            if state == "open":
                raise CircuitOpen(self.reset_seconds - (self._clock() - self._opened_at))
            if state == "half-open":
                if self._trial_in_flight:
                    raise CircuitOpen(1.0)
                self._trial_in_flight = True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._trial_in_flight = False

    def record_failure(self) -> None:
        with self._lock:
            self._trial_in_flight = False
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._opened_at = self._clock()
