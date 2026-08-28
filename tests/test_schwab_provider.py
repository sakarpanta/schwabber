from datetime import date

import pytest

from schwabber.config import Settings
from schwabber.errors import SchwabReauthRequired
from schwabber.providers.schwab import SchwabMarketProvider, create_schwab_provider


class Response:
    status_code = 200
    headers: dict[str, str] = {}

    def __init__(self, body: dict):
        self._body = body

    def json(self) -> dict:
        return self._body


@pytest.mark.asyncio
async def test_factory_requires_token_file(tmp_path) -> None:
    settings = Settings.from_mapping(
        {
            "SCHWABBER_API_KEY": "k" * 32,
            "SCHWAB_CLIENT_ID": "id",
            "SCHWAB_CLIENT_SECRET": "secret",
            "SCHWAB_TOKEN_PATH": str(tmp_path / "missing.json"),
        }
    )
    with pytest.raises(SchwabReauthRequired):
        await create_schwab_provider(settings)


@pytest.mark.asyncio
async def test_quotes_normalize_payload() -> None:
    class Client:
        async def get_quotes(self, symbols):
            return Response(
                {
                    "AMD": {
                        "assetMainType": "EQUITY",
                        "quote": {"bidPrice": 172.3, "lastPrice": 172.34},
                    }
                }
            )

    result = await SchwabMarketProvider(Client()).quotes(("AMD",))
    assert result[0].bid_price == 172.3


@pytest.mark.asyncio
async def test_history_converts_epoch_milliseconds() -> None:
    class Client:
        async def get_price_history(self, **kwargs):
            return Response(
                {
                    "candles": [
                        {
                            "datetime": 1785542400000,
                            "open": 170,
                            "high": 174,
                            "low": 169,
                            "close": 173,
                            "volume": 42,
                        }
                    ]
                }
            )

    result = await SchwabMarketProvider(Client()).history(
        "AMD", date(2026, 8, 1), date(2026, 8, 2), "1d", False
    )
    assert result[0].open == 170
    assert result[0].timestamp.tzinfo is not None
