from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request

from schwabber.api.dependencies import market_service
from schwabber.errors import InvalidRequest
from schwabber.schemas.common import CacheMeta, ResponseMeta, SuccessEnvelope
from schwabber.schemas.market import (
    Candle,
    Instrument,
    MarketHours,
    Mover,
    OptionContract,
    Quote,
)
from schwabber.services.market import MarketService, ServiceResult

router = APIRouter(prefix="/v1", tags=["market data"])


def envelope(request: Request, result: ServiceResult) -> SuccessEnvelope:
    return SuccessEnvelope(
        data=result.data,
        meta=ResponseMeta(
            source="schwab",
            retrieved_at=result.retrieved_at,
            request_id=request.state.request_id,
            cache=CacheMeta(hit=result.cache_hit, age_seconds=result.cache_age_seconds),
            result_count=len(result.data) if isinstance(result.data, list) else 1,
            truncated=result.truncated,
        ),
    )


@router.get(
    "/quotes",
    operation_id="get_quotes",
    summary="Get current quotes",
    description=(
        "Return normalized Schwab quote data for 1-25 symbols. Use this for "
        "current price, bid/ask, mark, daily range, volume, and quote freshness."
    ),
    response_model=SuccessEnvelope[list[Quote]],
    response_model_exclude_none=True,
)
async def get_quotes(
    request: Request,
    symbols: str = Query(
        min_length=1,
        description="One to 25 ticker symbols separated by commas.",
    ),
    service: MarketService = Depends(market_service),
) -> SuccessEnvelope[list[Quote]]:
    normalized = tuple(
        dict.fromkeys(
            symbol.strip().upper() for symbol in symbols.split(",") if symbol.strip()
        )
    )
    if not 1 <= len(normalized) <= 25:
        raise InvalidRequest("quotes require between 1 and 25 symbols")
    return envelope(request, await service.quotes(normalized))


@router.get(
    "/history/{symbol}",
    operation_id="get_price_history",
    summary="Get price history",
    description=(
        "Return normalized Schwab OHLCV candles for one symbol. Use this for "
        "returns, trends, chart analysis, and technical indicator calculations."
    ),
    response_model=SuccessEnvelope[list[Candle]],
    response_model_exclude_none=True,
)
async def get_price_history(
    request: Request,
    symbol: str = Path(
        min_length=1,
        max_length=20,
        description="Ticker symbol whose candles should be returned.",
    ),
    start: date | None = Query(
        None,
        description="First calendar date to include; defaults to one year ago.",
    ),
    end: date | None = Query(
        None,
        description="Last calendar date to include; defaults to today.",
    ),
    frequency: Literal["1m", "5m", "15m", "30m", "1d", "1w"] = Query(
        "1d",
        description="Candle interval: intraday minutes, daily, or weekly.",
    ),
    extended_hours: bool = Query(
        False,
        description="Include eligible extended-hours trading when true.",
    ),
    service: MarketService = Depends(market_service),
) -> SuccessEnvelope[list[Candle]]:
    effective_end = end or date.today()
    effective_start = start or effective_end - timedelta(days=365)
    return envelope(
        request,
        await service.history(
            symbol.upper(), effective_start, effective_end, frequency, extended_hours
        ),
    )


@router.get(
    "/instruments/{symbol}",
    operation_id="get_instrument",
    summary="Get an instrument profile",
    description=(
        "Return normalized Schwab identity and available snapshot fundamental "
        "fields for one instrument. Fields vary by security and may be absent."
    ),
    response_model=SuccessEnvelope[Instrument],
    response_model_exclude_none=True,
)
async def get_instrument(
    request: Request,
    symbol: str = Path(
        min_length=1,
        max_length=20,
        description="Ticker symbol whose instrument profile should be returned.",
    ),
    service: MarketService = Depends(market_service),
) -> SuccessEnvelope[Instrument]:
    return envelope(request, await service.instrument(symbol.upper()))


@router.get(
    "/options/{symbol}",
    operation_id="get_option_chain",
    summary="Get an option chain",
    description=(
        "Return a bounded Schwab option chain with prices, volume, open interest, "
        "implied volatility, and available Greeks for one underlying symbol."
    ),
    response_model=SuccessEnvelope[list[OptionContract]],
    response_model_exclude_none=True,
)
async def get_option_chain(
    request: Request,
    symbol: str = Path(
        min_length=1,
        max_length=20,
        description="Underlying ticker symbol for the option chain.",
    ),
    from_date: date | None = Query(
        None,
        description="Earliest expiration date; defaults to today.",
    ),
    to_date: date | None = Query(
        None,
        description="Latest expiration date; defaults to 45 days from the start.",
    ),
    put_call: Literal["ALL", "CALL", "PUT"] = Query(
        "ALL",
        description="Return calls, puts, or both contract types.",
    ),
    strike_count: int = Query(
        10,
        ge=1,
        le=50,
        description="Number of strikes around the underlying price, from 1 to 50.",
    ),
    minimum_open_interest: int = Query(
        0,
        ge=0,
        description="Exclude contracts below this open-interest value.",
    ),
    service: MarketService = Depends(market_service),
) -> SuccessEnvelope[list[OptionContract]]:
    effective_from = from_date or date.today()
    effective_to = to_date or effective_from + timedelta(days=45)
    return envelope(
        request,
        await service.options(
            symbol.upper(),
            effective_from,
            effective_to,
            put_call,
            strike_count,
            minimum_open_interest,
        ),
    )


@router.get(
    "/movers/{index}",
    operation_id="get_movers",
    summary="Get market movers",
    description=(
        "Return a bounded Schwab list of rising, falling, or actively traded "
        "symbols for a supported index or exchange."
    ),
    response_model=SuccessEnvelope[list[Mover]],
    response_model_exclude_none=True,
)
async def get_movers(
    request: Request,
    index: Literal["$DJI", "$COMPX", "$SPX", "NYSE", "NASDAQ"] = Path(
        description="Supported index or exchange universe to scan."
    ),
    direction: Literal["UP", "DOWN", "TRADES"] = Query(
        "UP",
        description="Rank symbols by gains, losses, or trading activity.",
    ),
    frequency: Literal[0, 1, 5, 10, 30, 60] = Query(
        10,
        description="Schwab mover update frequency in minutes.",
    ),
    limit: int = Query(
        10,
        ge=1,
        le=50,
        description="Maximum number of mover records to return, from 1 to 50.",
    ),
    service: MarketService = Depends(market_service),
) -> SuccessEnvelope[list[Mover]]:
    return envelope(request, await service.movers(index, direction, frequency, limit))


@router.get(
    "/market-hours",
    operation_id="get_market_hours",
    summary="Get market hours",
    description=(
        "Return Schwab equity and option trading-session status and timestamps "
        "for a date. Use this before assuming a regular market session."
    ),
    response_model=SuccessEnvelope[list[MarketHours]],
    response_model_exclude_none=True,
)
async def get_market_hours(
    request: Request,
    day: date | None = Query(
        None,
        description="Calendar date to inspect; defaults to today.",
    ),
    markets: Literal["equity", "option", "equity,option"] = Query(
        "equity,option",
        description="Market categories to return: equity, option, or both.",
    ),
    service: MarketService = Depends(market_service),
) -> SuccessEnvelope[list[MarketHours]]:
    return envelope(
        request,
        await service.market_hours(tuple(markets.split(",")), day or date.today()),
    )
