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
    response_model=SuccessEnvelope[list[Quote]],
    response_model_exclude_none=True,
)
async def get_quotes(
    request: Request,
    symbols: str = Query(min_length=1),
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
    response_model=SuccessEnvelope[list[Candle]],
    response_model_exclude_none=True,
)
async def get_price_history(
    request: Request,
    symbol: str = Path(min_length=1, max_length=20),
    start: date | None = None,
    end: date | None = None,
    frequency: Literal["1m", "5m", "15m", "30m", "1d", "1w"] = "1d",
    extended_hours: bool = False,
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
    response_model=SuccessEnvelope[Instrument],
    response_model_exclude_none=True,
)
async def get_instrument(
    request: Request,
    symbol: str = Path(min_length=1, max_length=20),
    service: MarketService = Depends(market_service),
) -> SuccessEnvelope[Instrument]:
    return envelope(request, await service.instrument(symbol.upper()))


@router.get(
    "/options/{symbol}",
    operation_id="get_option_chain",
    response_model=SuccessEnvelope[list[OptionContract]],
    response_model_exclude_none=True,
)
async def get_option_chain(
    request: Request,
    symbol: str = Path(min_length=1, max_length=20),
    from_date: date | None = None,
    to_date: date | None = None,
    put_call: Literal["ALL", "CALL", "PUT"] = "ALL",
    strike_count: int = Query(10, ge=1, le=50),
    minimum_open_interest: int = Query(0, ge=0),
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
    response_model=SuccessEnvelope[list[Mover]],
    response_model_exclude_none=True,
)
async def get_movers(
    request: Request,
    index: Literal["$DJI", "$COMPX", "$SPX", "NYSE", "NASDAQ"],
    direction: Literal["UP", "DOWN", "TRADES"] = "UP",
    frequency: Literal[0, 1, 5, 10, 30, 60] = 10,
    limit: int = Query(10, ge=1, le=50),
    service: MarketService = Depends(market_service),
) -> SuccessEnvelope[list[Mover]]:
    return envelope(request, await service.movers(index, direction, frequency, limit))


@router.get(
    "/market-hours",
    operation_id="get_market_hours",
    response_model=SuccessEnvelope[list[MarketHours]],
    response_model_exclude_none=True,
)
async def get_market_hours(
    request: Request,
    day: date | None = None,
    markets: Literal["equity", "option", "equity,option"] = "equity,option",
    service: MarketService = Depends(market_service),
) -> SuccessEnvelope[list[MarketHours]]:
    return envelope(
        request,
        await service.market_hours(tuple(markets.split(",")), day or date.today()),
    )
