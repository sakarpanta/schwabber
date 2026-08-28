from datetime import date
from typing import Protocol

from schwabber.schemas.market import (
    Candle,
    Instrument,
    MarketHours,
    Mover,
    OptionContract,
    Quote,
)


class MarketProvider(Protocol):
    async def quotes(self, symbols: tuple[str, ...]) -> list[Quote]: ...
    async def instrument(self, symbol: str) -> Instrument: ...
    async def history(
        self, symbol: str, start: date, end: date, frequency: str, extended: bool
    ) -> list[Candle]: ...
    async def options(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
        put_call: str,
        strike_count: int,
    ) -> list[OptionContract]: ...
    async def movers(
        self, index: str, direction: str, frequency: int
    ) -> list[Mover]: ...
    async def market_hours(
        self, markets: tuple[str, ...], day: date
    ) -> list[MarketHours]: ...
