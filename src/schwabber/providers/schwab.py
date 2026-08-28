from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from typing import Any, Literal

import httpx
from authlib.integrations.base_client.errors import (  # type: ignore[import-untyped]
    OAuthError,
)

from schwabber.config import Settings
from schwabber.errors import (
    RateLimited,
    ResourceNotFound,
    SchwabReauthRequired,
    UpstreamFailure,
)
from schwabber.retry import retry_async
from schwabber.schemas.market import (
    Candle,
    Instrument,
    MarketHours,
    Mover,
    OptionContract,
    Quote,
)


def _epoch_ms(value: int | None) -> datetime | None:
    return datetime.fromtimestamp(value / 1000, tz=UTC) if value is not None else None


def _field(*sources: dict[str, Any], names: tuple[str, ...]) -> Any:
    for source in sources:
        for name in names:
            if name in source:
                return source[name]
    return None


async def create_schwab_provider(settings: Settings) -> SchwabMarketProvider:
    if not settings.schwab_configured or not settings.token_path.exists():
        raise SchwabReauthRequired("Run: schwabber auth login")
    assert settings.schwab_client_id is not None
    assert settings.schwab_client_secret is not None
    from schwab.auth import client_from_token_file  # type: ignore[import-untyped]

    client = client_from_token_file(
        str(settings.token_path),
        settings.schwab_client_id,
        settings.schwab_client_secret,
        asyncio=True,
        enforce_enums=False,
    )
    client.set_timeout(httpx.Timeout(25.0, connect=3.0, read=10.0))
    return SchwabMarketProvider(client)


class _TransientSchwabError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class SchwabMarketProvider:
    def __init__(
        self, client: Any, *, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    ):
        self._client = client
        self._sleep = sleep

    async def _json(
        self, operation: Callable[[], Awaitable[Any]] | Awaitable[Any]
    ) -> dict[str, Any]:
        async def attempt() -> Any:
            response = await operation() if callable(operation) else await operation
            if response.status_code == 429 or response.status_code >= 500:
                raise _TransientSchwabError(response.status_code)
            return response

        try:
            async with asyncio.timeout(25):
                response = await retry_async(
                    attempt,
                    should_retry=lambda exc: isinstance(exc, _TransientSchwabError),
                    sleep=self._sleep,
                )
        except TimeoutError as exc:
            raise UpstreamFailure("Schwab operation exceeded 25 seconds") from exc
        except OAuthError as exc:
            raise SchwabReauthRequired(
                "Schwab authorization must be renewed; run schwabber auth login"
            ) from exc
        except _TransientSchwabError as exc:
            if exc.status_code == 429:
                raise RateLimited("Schwab request limit reached") from exc
            raise UpstreamFailure(f"Schwab returned HTTP {exc.status_code}") from exc
        if response.status_code == 404:
            raise ResourceNotFound("Schwab resource not found")
        if response.status_code in {401, 403}:
            raise SchwabReauthRequired(
                "Schwab authorization must be renewed; run schwabber auth login"
            )
        if response.status_code >= 400:
            raise UpstreamFailure(f"Schwab returned HTTP {response.status_code}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise UpstreamFailure("Schwab returned a non-object response")
        return payload

    async def quotes(self, symbols: tuple[str, ...]) -> list[Quote]:
        payload = await self._json(lambda: self._client.get_quotes(list(symbols)))
        result: list[Quote] = []
        for symbol in symbols:
            item = payload.get(symbol, {})
            quote = item.get("quote", {})
            regular = item.get("regular", {})
            reference = item.get("reference", {})
            result.append(
                Quote(
                    symbol=symbol,
                    asset_type=item.get("assetMainType"),
                    last_price=_field(
                        quote, regular, names=("lastPrice", "regularMarketLastPrice")
                    ),
                    bid_price=quote.get("bidPrice"),
                    ask_price=quote.get("askPrice"),
                    mark=_field(quote, names=("mark", "markPrice")),
                    open_price=_field(
                        regular, quote, names=("regularMarketOpen", "openPrice")
                    ),
                    high_price=_field(
                        regular, quote, names=("regularMarketHigh", "highPrice")
                    ),
                    low_price=_field(
                        regular, quote, names=("regularMarketLow", "lowPrice")
                    ),
                    close_price=_field(
                        regular, quote, names=("regularMarketLastPrice", "closePrice")
                    ),
                    total_volume=quote.get("totalVolume"),
                    quote_time=_epoch_ms(quote.get("quoteTime")),
                    trade_time=_epoch_ms(quote.get("tradeTime")),
                    is_realtime=reference.get("isRealtime"),
                )
            )
        return result

    async def instrument(self, symbol: str) -> Instrument:
        payload = await self._json(
            lambda: self._client.get_instruments(symbol, projection="FUNDAMENTAL")
        )
        item = next(iter(payload.get("instruments", [])), None)
        if item is None:
            raise ResourceNotFound(f"No instrument found for {symbol}")
        fundamental = item.get("fundamental", {})
        return Instrument(
            symbol=item.get("symbol", symbol),
            description=item.get("description"),
            exchange=item.get("exchange"),
            asset_type=item.get("assetType"),
            market_cap=fundamental.get("marketCap"),
            pe_ratio=fundamental.get("peRatio"),
            eps=fundamental.get("epsTTM"),
            dividend_yield=fundamental.get("divYield"),
            beta=fundamental.get("beta"),
            shares_outstanding=fundamental.get("sharesOutstanding"),
            week_52_high=fundamental.get("high52"),
            week_52_low=fundamental.get("low52"),
        )

    async def history(
        self, symbol: str, start: date, end: date, frequency: str, extended: bool
    ) -> list[Candle]:
        mapping = {
            "1m": ("minute", 1),
            "5m": ("minute", 5),
            "15m": ("minute", 15),
            "30m": ("minute", 30),
            "1d": ("daily", 1),
            "1w": ("weekly", 1),
        }
        frequency_type, frequency_value = mapping[frequency]
        payload = await self._json(
            lambda: self._client.get_price_history(
                symbol=symbol,
                start_datetime=datetime.combine(start, datetime.min.time(), tzinfo=UTC),
                end_datetime=datetime.combine(end, datetime.max.time(), tzinfo=UTC),
                frequency_type=frequency_type,
                frequency=frequency_value,
                need_extended_hours_data=extended,
            )
        )
        return [
            Candle(
                timestamp=_epoch_ms(item["datetime"])
                or datetime.fromtimestamp(0, tz=UTC),
                open=item["open"],
                high=item["high"],
                low=item["low"],
                close=item["close"],
                volume=item["volume"],
            )
            for item in payload.get("candles", [])
        ]

    async def options(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
        put_call: str,
        strike_count: int,
    ) -> list[OptionContract]:
        payload = await self._json(
            lambda: self._client.get_option_chain(
                symbol,
                contract_type=put_call,
                strike_count=strike_count,
                from_date=from_date,
                to_date=to_date,
            )
        )
        results: list[OptionContract] = []
        for map_name in ("callExpDateMap", "putExpDateMap"):
            side: Literal["CALL", "PUT"] = (
                "CALL" if map_name == "callExpDateMap" else "PUT"
            )
            for expiry_key, strikes in payload.get(map_name, {}).items():
                expiry = date.fromisoformat(expiry_key.split(":", 1)[0])
                for strike_key, contracts in strikes.items():
                    for item in contracts:
                        results.append(
                            OptionContract(
                                symbol=item["symbol"],
                                underlying=payload.get("symbol", symbol),
                                expiration=expiry,
                                strike=float(strike_key),
                                put_call=side,
                                bid=item.get("bid"),
                                ask=item.get("ask"),
                                last=item.get("last"),
                                mark=item.get("mark"),
                                volume=item.get("totalVolume"),
                                open_interest=item.get("openInterest"),
                                implied_volatility=item.get("volatility"),
                                delta=item.get("delta"),
                                gamma=item.get("gamma"),
                                theta=item.get("theta"),
                                vega=item.get("vega"),
                                rho=item.get("rho"),
                                quote_time=_epoch_ms(item.get("quoteTimeInLong")),
                                is_realtime=item.get("realtime"),
                            )
                        )
        return results

    async def movers(self, index: str, direction: str, frequency: int) -> list[Mover]:
        payload = await self._json(
            lambda: self._client.get_movers(
                index, sort_order=direction, frequency=frequency
            )
        )
        return [
            Mover(
                symbol=item["symbol"],
                description=item.get("description"),
                last_price=item.get("lastPrice"),
                change=item.get("netChange"),
                percent_change=item.get("percentChange"),
                volume=item.get("totalVolume"),
            )
            for item in payload.get("screeners", [])
        ]

    async def market_hours(
        self, markets: tuple[str, ...], day: date
    ) -> list[MarketHours]:
        payload = await self._json(
            lambda: self._client.get_market_hours(list(markets), date=day)
        )
        results: list[MarketHours] = []
        for market, products in payload.items():
            for product, item in products.items():
                sessions = item.get("sessionHours", {})
                pre = (sessions.get("preMarket") or [{}])[0]
                regular = (sessions.get("regularMarket") or [{}])[0]
                post = (sessions.get("postMarket") or [{}])[0]
                results.append(
                    MarketHours(
                        market=market,
                        product=product,
                        date=day,
                        is_open=item.get("isOpen", False),
                        pre_market_start=pre.get("start"),
                        pre_market_end=pre.get("end"),
                        regular_start=regular.get("start"),
                        regular_end=regular.get("end"),
                        post_market_start=post.get("start"),
                        post_market_end=post.get("end"),
                    )
                )
        return results
