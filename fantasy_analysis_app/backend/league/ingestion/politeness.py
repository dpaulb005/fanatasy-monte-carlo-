"""Politeness middleware for ESPN requests.

``espn-api`` has no built-in rate-limit or backoff handling, so we add our own:
serialized calls with a jittered delay and exponential backoff on transient
errors. Backfill volume is small (a few hundred requests), so this keeps us
comfortably polite. Delays are injectable so tests run instantly.

``call`` deliberately retries on ANY exception: ESPN's edge intermittently
returns 404 for perfectly valid leagues after request bursts (observed live,
2026-07-15), which espn-api surfaces as ``ESPNInvalidLeague`` — so even
"fatal-looking" errors get ``max_retries`` attempts before propagating.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class Politeness:
    def __init__(
        self,
        base_delay: float = 0.5,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.base_delay = base_delay
        self.max_retries = max_retries
        self._sleep = sleep
        self._rng = rng or random.Random()

    def pause(self) -> None:
        """Jittered inter-request delay."""
        if self.base_delay > 0:
            self._sleep(self.base_delay * (0.5 + self._rng.random()))

    def call(self, fn: Callable[[], T]) -> T:
        """Run ``fn`` with exponential backoff + jitter on transient failure."""
        attempt = 0
        while True:
            try:
                return fn()
            except Exception:
                attempt += 1
                if attempt > self.max_retries:
                    raise
                backoff = self.base_delay * (2**attempt) * (0.5 + self._rng.random())
                self._sleep(backoff)
