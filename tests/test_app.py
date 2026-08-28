from fastapi.testclient import TestClient

from schwabber.app import build_app
from schwabber.cache import TtlLruCache
from schwabber.config import Settings
from schwabber.services.market import MarketService


def settings() -> Settings:
    return Settings.from_mapping({"SCHWABBER_API_KEY": "k" * 32})


def test_health_is_public() -> None:
    assert TestClient(build_app(settings())).get("/healthz").json() == {
        "status": "alive"
    }


def test_v1_requires_bearer_key() -> None:
    client = TestClient(build_app(settings()))
    assert client.get("/v1/status").status_code == 401
    response = client.get("/v1/status", headers={"Authorization": f"Bearer {'k' * 32}"})
    assert response.status_code == 200


def test_status_reports_sec_readiness() -> None:
    configured = Settings.from_mapping(
        {
            "SCHWABBER_API_KEY": "k" * 32,
            "SEC_USER_AGENT": "Schwabber operator@example.com",
        }
    )
    client = TestClient(build_app(configured, sec_service=object()))
    response = client.get("/v1/status", headers={"Authorization": f"Bearer {'k' * 32}"})
    assert response.status_code == 200
    assert response.json()["data"]["sec"] == {"configured": True, "ready": True}


def test_validation_errors_use_error_envelope() -> None:
    class Provider:
        async def quotes(self, symbols):
            return []

    client = TestClient(build_app(settings(), MarketService(Provider(), TtlLruCache())))
    response = client.get(
        "/v1/quotes?symbols=" + ",".join(f"S{i}" for i in range(26)),
        headers={"Authorization": f"Bearer {'k' * 32}"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_openapi_has_stable_ids_and_bearer_security() -> None:
    schema = build_app(settings()).openapi()
    operations = {
        operation["operationId"]
        for path in schema["paths"].values()
        for operation in path.values()
        if isinstance(operation, dict) and "operationId" in operation
    }
    assert {
        "get_quotes",
        "get_price_history",
        "get_instrument",
        "get_option_chain",
        "get_movers",
        "get_market_hours",
        "get_service_status",
    } <= operations
    assert "HTTPBearer" in schema["components"]["securitySchemes"]
    assert schema["servers"][0]["url"] == "http://127.0.0.1:8000"


def test_authenticated_burst_is_limited() -> None:
    client = TestClient(build_app(settings()))
    headers = {"Authorization": f"Bearer {'k' * 32}"}
    for _ in range(10):
        assert client.get("/v1/status", headers=headers).status_code == 200
    limited = client.get("/v1/status", headers=headers)
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "1"


def test_forwarded_ip_is_ignored_from_non_loopback_client() -> None:
    app = build_app(settings())
    with TestClient(app, client=("203.0.113.10", 50000)) as client:
        response = client.get(
            "/v1/status", headers={"X-Forwarded-For": "198.51.100.25"}
        )
    assert response.status_code == 401
    assert app.state.last_auth_client_ip == "203.0.113.10"
