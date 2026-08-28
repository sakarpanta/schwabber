from datetime import UTC, datetime

from fastapi import APIRouter, Request

from schwabber import __version__
from schwabber.schemas.common import CacheMeta, ResponseMeta, SuccessEnvelope

router = APIRouter(prefix="/v1", tags=["service"])


@router.get("/status", operation_id="get_service_status")
async def get_service_status(request: Request) -> SuccessEnvelope[dict[str, object]]:
    now = datetime.now(UTC)
    settings = request.app.state.settings
    data: dict[str, object] = {
        "version": __version__,
        "cache_available": True,
        "schwab": {
            "configured": settings.schwab_configured,
            "ready": request.app.state.market_service is not None,
        },
        "sec": {"configured": settings.sec_configured, "ready": False},
    }
    return SuccessEnvelope(
        data=data,
        meta=ResponseMeta(
            source="application",
            retrieved_at=now,
            request_id=request.state.request_id,
            cache=CacheMeta(hit=False, age_seconds=0),
            result_count=1,
        ),
    )
