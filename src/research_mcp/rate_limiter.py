"""Rate limiter for API calls."""

from __future__ import annotations

import asyncio
from collections import deque
from time import time


class RateLimiter:
    """Token bucket rate limiter."""

    def __init__(self, rate: float, burst: int = 1):
        """Initialize rate limiter.

        Args:
            rate: Tokens per second
            burst: Maximum number of tokens that can be accumulated
        """
        self.rate = rate  # tokens per second
        self.burst = burst  # max tokens
        self.tokens = burst  # current tokens
        self.last_update = time()
        self.lock = asyncio.Lock()
        # Track request timestamps for debugging
        self.request_times = deque(maxlen=100)

    async def acquire(self):
        """Acquire a token, waiting if necessary."""
        async with self.lock:
            now = time()
            time_passed = now - self.last_update
            self.tokens = min(self.burst, self.tokens + time_passed * self.rate)
            self.last_update = now

            if self.tokens < 1:
                wait_time = (1 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 1  # We've waited long enough for one token
                self.last_update = time()

            self.tokens -= 1
            self.request_times.append(time())

    def get_request_rate(self, window: float = 1.0) -> float:
        """Calculate current request rate over window seconds."""
        now = time()
        recent = [t for t in self.request_times if now - t <= window]
        return len(recent) / window if recent else 0
