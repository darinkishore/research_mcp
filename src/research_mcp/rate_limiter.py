import asyncio
import logging
import time


logger = logging.getLogger('rate_limiter')


class RateLimiter:
    """Asynchronous rate limiter that limits the rate of actions per period."""

    def __init__(self, max_calls: int, period: float):
        self.max_calls = max_calls
        self.period = period
        self.lock = asyncio.Lock()
        self.tokens = max_calls
        self.updated_at = time.monotonic()

    async def acquire(self):
        async with self.lock:
            now = time.monotonic()
            elapsed = now - self.updated_at
            self.updated_at = now
            # Refill tokens based on the elapsed time
            self.tokens += elapsed * (self.max_calls / self.period)
            self.tokens = min(self.tokens, self.max_calls)

            if self.tokens >= 1:
                self.tokens -= 1
                logger.debug(f'Token acquired. Tokens left: {self.tokens}')
                return

            # Calculate the time to wait
            wait_time = (1 - self.tokens) * (self.period / self.max_calls)
            logger.debug(f'Rate limit reached. Waiting for {wait_time:.2f} seconds.')

            # Add small delay to prevent tight loops
            await asyncio.sleep(max(0.03, wait_time))
            self.tokens = 0
            self.updated_at = time.monotonic()
            logger.debug('Resuming after wait.')
