from datetime import UTC, datetime

from fastapi.testclient import TestClient

from schwabber.app import build_app
from schwabber.config import Settings
from schwabber.schemas.market import Quote
from schwabber.services.market import ServiceResult


class Service:
    async def quotes(self, symbols):
        return ServiceResult(
            [Quote(symbol=s, last_price=100.0) for s in symbols],
            datetime(2026, 8, 28, tzinfo=UTC),
            False,
            0,
        )


def test_quotes_route_returns_envelope() -> None:
    app = build_app(
        Settings.from_mapping({"SCHWABBER_API_KEY": "k" * 32}), market_service=Service()
    )
    response = TestClient(app).get(
        "/v1/quotes?symbols=AMD,AAPL", headers={"Authorization": f"Bearer {'k' * 32}"}
    )
    assert response.status_code == 200
    assert response.json()["meta"]["source"] == "schwab"
    assert len(response.json()["data"]) == 2
