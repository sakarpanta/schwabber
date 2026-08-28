import pytest

from schwabber.retry import retry_async


@pytest.mark.asyncio
async def test_retry_stops_after_two_retries() -> None:
    calls = 0

    async def failing() -> int:
        nonlocal calls
        calls += 1
        raise RuntimeError("transient")

    async def no_sleep(_: float) -> None:
        return None

    with pytest.raises(RuntimeError, match="transient"):
        await retry_async(
            failing,
            should_retry=lambda _: True,
            attempts=3,
            sleep=no_sleep,
        )
    assert calls == 3
