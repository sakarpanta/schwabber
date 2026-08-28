from typing import cast

from fastapi import Request

from schwabber.errors import ProviderUnavailable
from schwabber.services.market import MarketService


def market_service(request: Request) -> MarketService:
    service = cast(MarketService | None, request.app.state.market_service)
    if service is None:
        raise ProviderUnavailable("Schwab is not configured or authorized")
    return service
