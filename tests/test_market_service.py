from datetime import date

import pytest

from schwabber.cache import TtlLruCache
from schwabber.errors import InvalidRequest
from schwabber.schemas.market import Quote
from schwabber.services.market import MarketService


class Provider:
    calls = 0

    async def quotes(self, symbols):
        self.calls += 1
        return [Quote(symbol=symbol, last_price=1.0) for symbol in symbols]


@pytest.mark.asyncio
async def test_quotes_report_cache_hit_on_second_call() -> None:
    provider = Provider()
    service = MarketService(provider, TtlLruCache())
    assert (await service.quotes(("AMD",))).cache_hit is False
    assert (await service.quotes(("AMD",))).cache_hit is True
    assert provider.calls == 1


def test_one_minute_history_rejects_more_than_ten_days() -> None:
    with pytest.raises(InvalidRequest, match="10 calendar days"):
        MarketService.validate_history_window(date(2026, 8, 1), date(2026, 8, 12), "1m")
