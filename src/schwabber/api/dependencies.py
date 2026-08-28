from typing import cast

from fastapi import Request

from schwabber.errors import ProviderUnavailable
from schwabber.services.market import MarketService
from schwabber.services.sec import SecResearchService


def market_service(request: Request) -> MarketService:
    service = cast(MarketService | None, request.app.state.market_service)
    if service is None:
        raise ProviderUnavailable("Schwab is not configured or authorized")
    return service


def sec_service(request: Request) -> SecResearchService:
    service = cast(SecResearchService | None, request.app.state.sec_service)
    if service is None:
        raise ProviderUnavailable("SEC is not configured")
    return service
