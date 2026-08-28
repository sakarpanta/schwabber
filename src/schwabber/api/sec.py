from typing import Literal

from fastapi import APIRouter, Depends, Query, Request

from schwabber.api.dependencies import sec_service
from schwabber.schemas.common import CacheMeta, ResponseMeta, SuccessEnvelope
from schwabber.schemas.sec import Filing, FinancialStatement
from schwabber.services.sec import SecResearchService

router = APIRouter(prefix="/v1", tags=["SEC research"])


def _envelope(request: Request, result):
    return SuccessEnvelope(
        data=result.data,
        meta=ResponseMeta(
            source="sec",
            retrieved_at=result.retrieved_at,
            request_id=request.state.request_id,
            cache=CacheMeta(hit=result.cache_hit, age_seconds=result.cache_age_seconds),
            result_count=len(result.data.periods)
            if hasattr(result.data, "periods")
            else len(result.data),
        ),
    )


@router.get(
    "/financials/{symbol}",
    operation_id="get_financials",
    response_model=SuccessEnvelope[FinancialStatement],
)
async def financials(
    request: Request,
    symbol: str,
    period_type: Literal["annual", "quarterly"] = "annual",
    count: int = Query(5, ge=1, le=20),
    service: SecResearchService = Depends(sec_service),
):
    return _envelope(request, await service.financials(symbol, period_type, count))


@router.get(
    "/filings/{symbol}",
    operation_id="get_filings",
    response_model=SuccessEnvelope[list[Filing]],
)
async def filings(
    request: Request,
    symbol: str,
    forms: str = "10-K,10-Q,8-K",
    count: int = Query(20, ge=1, le=100),
    service: SecResearchService = Depends(sec_service),
):
    return _envelope(
        request,
        await service.filings(
            symbol,
            tuple(f.strip().upper() for f in forms.split(",") if f.strip()),
            count,
        ),
    )
