import math
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic


@dataclass
class _BucketState:
    tokens: float
    updated_at: float


class TokenBucket:
    def __init__(
        self,
        *,
        rate_per_second: float,
        capacity: int,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if rate_per_second <= 0 or capacity <= 0:
            raise ValueError("rate and capacity must be positive")
        self._rate, self._capacity, self._clock = (
            rate_per_second,
            float(capacity),
            clock,
        )
        self._states: dict[str, _BucketState] = {}

    def consume(self, key: str) -> int | None:
        now = self._clock()
        state = self._states.setdefault(key, _BucketState(self._capacity, now))
        state.tokens = min(
            self._capacity, state.tokens + max(now - state.updated_at, 0.0) * self._rate
        )
        state.updated_at = now
        if state.tokens >= 1:
            state.tokens -= 1
            return None
        return max(1, math.ceil((1 - state.tokens) / self._rate))
