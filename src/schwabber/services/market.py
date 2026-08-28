from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TypeVar, cast

from schwabber.cache import TtlLruCache
from schwabber.errors import InvalidRequest
from schwabber.providers.base import MarketProvider
from schwabber.schemas.market import (
    Candle,
    Instrument,
    MarketHours,
    Mover,
    OptionContract,
    Quote,
)

T = TypeVar("T")


@dataclass(frozen=True)
class ServiceResult[T]:
    data: T
    retrieved_at: datetime
    cache_hit: bool
    cache_age_seconds: int
    truncated: bool = False


class MarketService:
    def __init__(
        self, provider: MarketProvider, cache: TtlLruCache[tuple[object, ...], object]
    ) -> None:
        self._provider = provider
        self._cache = cache

    async def _load(
        self, key: tuple[object, ...], ttl: int, loader
    ) -> ServiceResult[T]:
        cached = self._cache.get(key)
        if cached is not None:
            value, age = cached
            result = cast(ServiceResult[T], value)
            return ServiceResult(
                result.data, result.retrieved_at, True, age, result.truncated
            )
        result = ServiceResult(await loader(), datetime.now(UTC), False, 0)
        self._cache.set(key, result, ttl)
        return result

    async def quotes(self, symbols: tuple[str, ...]) -> ServiceResult[list[Quote]]:
        if not 1 <= len(symbols) <= 25:
            raise InvalidRequest("quotes require between 1 and 25 symbols")
        return await self._load(
            ("quotes", *symbols), 5, lambda: self._provider.quotes(symbols)
        )

    async def instrument(self, symbol: str) -> ServiceResult[Instrument]:
        return await self._load(
            ("instrument", symbol), 300, lambda: self._provider.instrument(symbol)
        )

    @staticmethod
    def validate_history_window(start: date, end: date, frequency: str) -> None:
        limits = {
            "1m": 10,
            "5m": 60,
            "15m": 60,
            "30m": 60,
            "1d": 5 * 366,
            "1w": 20 * 366,
        }
        if start > end:
            raise InvalidRequest("start must not be after end")
        if frequency not in limits:
            raise InvalidRequest(f"Unsupported history frequency: {frequency}")
        if (end - start).days > limits[frequency]:
            raise InvalidRequest(
                f"{frequency} history supports at most "
                f"{limits[frequency]} calendar days"
            )

    async def history(
        self, symbol: str, start: date, end: date, frequency: str, extended: bool
    ) -> ServiceResult[list[Candle]]:
        self.validate_history_window(start, end, frequency)
        key = ("history", symbol, start, end, frequency, extended)
        cached = self._cache.get(key)
        if cached is not None:
            value, age = cached
            result = cast(ServiceResult[list[Candle]], value)
            return ServiceResult(
                result.data, result.retrieved_at, True, age, result.truncated
            )
        values = await self._provider.history(symbol, start, end, frequency, extended)
        result = ServiceResult(
            values[-500:], datetime.now(UTC), False, 0, len(values) > 500
        )
        self._cache.set(
            key, result, 15 if frequency != "1d" and frequency != "1w" else 300
        )
        return result

    async def options(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
        put_call: str,
        strike_count: int,
        minimum_open_interest: int = 0,
    ) -> ServiceResult[list[OptionContract]]:
        if (
            from_date > to_date
            or put_call not in {"ALL", "CALL", "PUT"}
            or not 1 <= strike_count <= 50
            or minimum_open_interest < 0
        ):
            raise InvalidRequest("invalid option filters")
        key = (
            "options",
            symbol,
            from_date,
            to_date,
            put_call,
            strike_count,
            minimum_open_interest,
        )
        cached = self._cache.get(key)
        if cached is not None:
            value, age = cached
            result = cast(ServiceResult[list[OptionContract]], value)
            return ServiceResult(
                result.data, result.retrieved_at, True, age, result.truncated
            )
        values = await self._provider.options(
            symbol, from_date, to_date, put_call, strike_count
        )
        values = [
            item
            for item in values
            if (item.open_interest or 0) >= minimum_open_interest
        ]
        result = ServiceResult(
            values[:200], datetime.now(UTC), False, 0, len(values) > 200
        )
        self._cache.set(key, result, 15)
        return result

    async def movers(
        self, index: str, direction: str, frequency: int, limit: int = 10
    ) -> ServiceResult[list[Mover]]:
        if not 1 <= limit <= 50:
            raise InvalidRequest("limit must be between 1 and 50")
        return await self._bounded(
            ("movers", index, direction, frequency, limit),
            30,
            lambda: self._provider.movers(index, direction, frequency),
            limit,
        )

    async def _bounded[T](
        self,
        key: tuple[object, ...],
        ttl: int,
        loader: Callable[[], Awaitable[list[T]]],
        limit: int,
    ) -> ServiceResult[list[T]]:
        cached = self._cache.get(key)
        if cached is not None:
            value, age = cached
            result = cast(ServiceResult[list[T]], value)
            return ServiceResult(
                result.data, result.retrieved_at, True, age, result.truncated
            )
        values = await loader()
        result = ServiceResult(
            values[:limit], datetime.now(UTC), False, 0, len(values) > limit
        )
        self._cache.set(key, result, ttl)
        return result

    async def market_hours(
        self, markets: tuple[str, ...], day: date
    ) -> ServiceResult[list[MarketHours]]:
        return await self._load(
            ("market_hours", *markets, day),
            60,
            lambda: self._provider.market_hours(markets, day),
        )
