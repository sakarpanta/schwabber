import asyncio
import random
from collections.abc import Awaitable, Callable
from time import monotonic


async def retry_async[T](
    operation: Callable[[], Awaitable[T]],
    *,
    should_retry: Callable[[Exception], bool],
    attempts: int = 3,
    deadline_seconds: float = 25,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    started = monotonic()
    for attempt in range(attempts):
        try:
            return await operation()
        except Exception as exc:
            final = attempt == attempts - 1
            delay = (2**attempt) + random.uniform(0, 0.25)
            if (
                final
                or not should_retry(exc)
                or monotonic() - started + delay >= deadline_seconds
            ):
                raise
            await sleep(delay)
    raise AssertionError("retry loop exhausted")
