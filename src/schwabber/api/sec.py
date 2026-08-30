from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request

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
    summary="Get normalized SEC financials",
    description=(
        "Return a bounded set of normalized annual or standalone-quarter facts "
        "from SEC company filings. Missing metrics remain null rather than zero."
    ),
    response_model=SuccessEnvelope[FinancialStatement],
)
async def financials(
    request: Request,
    symbol: str = Path(
        min_length=1,
        max_length=20,
        description="Ticker symbol whose SEC company facts should be normalized.",
    ),
    period_type: Literal["annual", "quarterly"] = Query(
        "annual",
        description="Return annual fiscal years or standalone fiscal quarters.",
    ),
    count: int = Query(
        5,
        ge=1,
        le=20,
        description="Maximum number of unique fiscal periods, from 1 to 20.",
    ),
    service: SecResearchService = Depends(sec_service),
):
    return _envelope(request, await service.financials(symbol, period_type, count))


@router.get(
    "/filings/{symbol}",
    operation_id="get_filings",
    summary="Get recent SEC filings",
    description=(
        "Return recent SEC filing metadata and direct primary-document URLs for "
        "one ticker, filtered to the requested form types."
    ),
    response_model=SuccessEnvelope[list[Filing]],
)
async def filings(
    request: Request,
    symbol: str = Path(
        min_length=1,
        max_length=20,
        description="Ticker symbol whose SEC filing metadata should be returned.",
    ),
    forms: str = Query(
        "10-K,10-Q,8-K",
        description="Comma-separated SEC form types, such as 10-K,10-Q,8-K.",
    ),
    count: int = Query(
        20,
        ge=1,
        le=100,
        description="Maximum number of matching filings, from 1 to 100.",
    ),
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
