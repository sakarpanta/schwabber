# Phase 3: Production and Public Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden Schwabber for a single-user public deployment, document private Custom GPT integration, and ship a credential-safe open-source repository with automated quality gates.

**Architecture:** The application keeps one worker and in-memory state, adds bounded token buckets at the API and SEC edges, and wraps both providers in deadline-aware retries. Structured logging, Caddy TLS termination, non-root containers, offline CI, and operator documentation complete the deployment boundary without adding accounts, trading, MCP, or news endpoints.

**Tech Stack:** Python 3.12+, FastAPI, httpx, schwab-py, Docker Compose, Caddy, GitHub Actions, pytest, Ruff, mypy

---

## File map

- `src/schwabber/rate_limit.py`: deterministic token bucket used for inbound and SEC limits.
- `src/schwabber/auth.py`: authenticated and invalid-attempt limits with trusted-proxy handling.
- `src/schwabber/providers/sec.py`: 5 request/second limiter, retry, and deadline.
- `src/schwabber/providers/schwab.py`: retryable response classification and operation deadline.
- `src/schwabber/logging.py`: JSON formatting and recursive secret redaction.
- `src/schwabber/app.py`: request logging and limiter lifecycle.
- `compose.yaml`: hardened local/ngrok service.
- `compose.vps.yaml`, `Caddyfile`: HTTPS-only VPS edge.
- `docs/gpt-action-setup.md`: exact private GPT Action workflow.
- `docs/deployment-vps.md`: exact Caddy/VPS workflow.
- `SECURITY.md`, `CONTRIBUTING.md`, `LICENSE`: public-project policy.
- `.github/workflows/ci.yml`: offline quality and image gates.
- `tests/`: rate, retry, timeout, redaction, OpenAPI, deployment, and package tests.

### Task 1: Implement deterministic token buckets

**Files:**
- Create: `src/schwabber/rate_limit.py`
- Create: `tests/test_rate_limit.py`

- [ ] **Step 1: Write failing refill and burst tests**

```python
# tests/test_rate_limit.py
from schwabber.rate_limit import TokenBucket


def test_bucket_allows_burst_then_reports_wait() -> None:
    now = [0.0]
    bucket = TokenBucket(rate_per_second=1.0, capacity=2, clock=lambda: now[0])
    assert bucket.consume("key") is None
    assert bucket.consume("key") is None
    assert bucket.consume("key") == 1


def test_bucket_refills_without_exceeding_capacity() -> None:
    now = [0.0]
    bucket = TokenBucket(rate_per_second=1.0, capacity=2, clock=lambda: now[0])
    bucket.consume("key")
    bucket.consume("key")
    now[0] = 5.0
    assert bucket.consume("key") is None
    assert bucket.consume("key") is None
    assert bucket.consume("key") == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_rate_limit.py -q`

Expected: FAIL because `TokenBucket` is absent.

- [ ] **Step 3: Implement the keyed bucket**

```python
# src/schwabber/rate_limit.py
import math
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic


@dataclass
class _BucketState:
    tokens: float
    updated_at: float


class TokenBucket:
    def __init__(
        self,
        *,
        rate_per_second: float,
        capacity: int,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if rate_per_second <= 0 or capacity <= 0:
            raise ValueError("rate and capacity must be positive")
        self._rate = rate_per_second
        self._capacity = float(capacity)
        self._clock = clock
        self._states: dict[str, _BucketState] = {}

    def consume(self, key: str) -> int | None:
        now = self._clock()
        state = self._states.setdefault(
            key,
            _BucketState(tokens=self._capacity, updated_at=now),
        )
        elapsed = max(now - state.updated_at, 0.0)
        state.tokens = min(self._capacity, state.tokens + elapsed * self._rate)
        state.updated_at = now
        if state.tokens >= 1.0:
            state.tokens -= 1.0
            return None
        return max(1, math.ceil((1.0 - state.tokens) / self._rate))
```

- [ ] **Step 4: Run limiter tests**

Run: `.venv/bin/pytest tests/test_rate_limit.py -q`

Expected: `2 passed`.

- [ ] **Step 5: Commit the primitive**

```bash
git add src/schwabber/rate_limit.py tests/test_rate_limit.py
git commit -m "feat: add deterministic rate limiter"
```

### Task 2: Enforce authenticated and invalid-authentication limits

**Files:**
- Modify: `src/schwabber/auth.py`
- Modify: `src/schwabber/app.py`
- Modify: `tests/test_app.py`

- [ ] **Step 1: Write failing auth-limit and proxy-trust tests**

```python
# Add to tests/test_app.py
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
            "/v1/status",
            headers={"X-Forwarded-For": "198.51.100.25"},
        )
    assert response.status_code == 401
    assert app.state.last_auth_client_ip == "203.0.113.10"
```

- [ ] **Step 2: Run auth tests to verify they fail**

Run: `.venv/bin/pytest tests/test_app.py -k "burst or forwarded" -q`

Expected: FAIL because requests are not rate limited and forwarded-address trust is absent.

- [ ] **Step 3: Add trusted client address and both limits**

```python
# Replace src/schwabber/auth.py
import hmac
import ipaddress

from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from schwabber.errors import RateLimited, Unauthorized
from schwabber.rate_limit import TokenBucket

bearer = HTTPBearer(auto_error=False)


def client_ip(request: Request) -> str:
    direct = request.client.host if request.client else "unknown"
    try:
        trusted = ipaddress.ip_address(direct).is_loopback
    except ValueError:
        trusted = False
    forwarded = request.headers.get("X-Forwarded-For")
    if trusted and forwarded:
        return forwarded.split(",", 1)[0].strip()
    return direct


async def require_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> None:
    expected = request.app.state.settings.api_key
    supplied = credentials.credentials if credentials else ""
    request_ip = client_ip(request)
    request.app.state.last_auth_client_ip = request_ip
    if not hmac.compare_digest(supplied, expected):
        retry_after = request.app.state.invalid_auth_limiter.consume(request_ip)
        if retry_after is not None:
            raise RateLimited(
                "Too many invalid authentication attempts",
                retry_after_seconds=retry_after,
            )
        raise Unauthorized("Missing or invalid API key")
    retry_after = request.app.state.authenticated_limiter.consume("operator")
    if retry_after is not None:
        raise RateLimited(
            "Middleware request limit exceeded",
            retry_after_seconds=retry_after,
        )
```

```python
# Add after app.state assignments in build_app in src/schwabber/app.py
from schwabber.rate_limit import TokenBucket


    app.state.authenticated_limiter = TokenBucket(
        rate_per_second=settings.requests_per_minute / 60,
        capacity=10,
    )
    app.state.invalid_auth_limiter = TokenBucket(
        rate_per_second=20 / 60,
        capacity=5,
    )
    app.state.last_auth_client_ip = None
```

- [ ] **Step 4: Run app tests**

Run: `.venv/bin/pytest tests/test_app.py -q`

Expected: all tests PASS, including a compact `429` envelope with `Retry-After`.

- [ ] **Step 5: Commit inbound limits**

```bash
git add src/schwabber/auth.py src/schwabber/app.py tests/test_app.py
git commit -m "feat: enforce API request limits"
```

### Task 3: Add SEC fair-access pacing, retries, and deadlines

**Files:**
- Modify: `src/schwabber/providers/sec.py`
- Modify: `tests/test_sec_provider.py`

- [ ] **Step 1: Write failing transient-response and timeout tests**

```python
# Add to tests/test_sec_provider.py
@pytest.mark.asyncio
async def test_sec_retries_transient_response_twice() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        status = 503 if calls < 3 else 200
        return httpx.Response(status, json={}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = HttpSecProvider(
        client,
        "Schwabber operator@example.com",
        sleep=lambda _: no_sleep(),
    )
    await provider._get("https://www.sec.gov/test.json")
    assert calls == 3
    await client.aclose()


async def no_sleep() -> None:
    return None
```

- [ ] **Step 2: Run the transient test to verify it fails**

Run: `.venv/bin/pytest tests/test_sec_provider.py -k retries -q`

Expected: FAIL because the adapter raises on the first `503` and has no injectable sleep.

- [ ] **Step 3: Wrap SEC calls with pacing and retry classification**

```python
# Replace the imports, constructor, and _get method in src/schwabber/providers/sec.py
import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import httpx

from schwabber.errors import RateLimited, ResourceNotFound, UpstreamFailure
from schwabber.rate_limit import TokenBucket
from schwabber.retry import retry_async


class _TransientSecError(Exception):
    def __init__(self, status_code: int, retry_after: int | None) -> None:
        self.status_code = status_code
        self.retry_after = retry_after


class HttpSecProvider:
    def __init__(
        self,
        client: httpx.AsyncClient,
        user_agent: str,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client
        self._sleep = sleep
        self._fair_access = TokenBucket(rate_per_second=5.0, capacity=5)
        self._headers = {
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json",
        }

    async def _get(self, url: str) -> dict[str, Any]:
        async def attempt() -> httpx.Response:
            wait = self._fair_access.consume("sec")
            while wait is not None:
                await self._sleep(float(wait))
                wait = self._fair_access.consume("sec")
            response = await self._client.get(url, headers=self._headers)
            if response.status_code == 429 or response.status_code >= 500:
                retry_header = response.headers.get("Retry-After")
                retry_after = int(retry_header) if retry_header and retry_header.isdigit() else None
                raise _TransientSecError(response.status_code, retry_after)
            return response

        try:
            async with asyncio.timeout(25):
                response = await retry_async(
                    attempt,
                    should_retry=lambda exc: isinstance(exc, _TransientSecError),
                    attempts=3,
                    deadline_seconds=25,
                    sleep=self._sleep,
                )
        except TimeoutError as exc:
            raise UpstreamFailure("SEC operation exceeded 25 seconds") from exc
        except _TransientSecError as exc:
            if exc.status_code == 429:
                raise RateLimited(
                    "SEC request limit reached",
                    retry_after_seconds=exc.retry_after,
                ) from exc
            raise UpstreamFailure(f"SEC returned HTTP {exc.status_code}") from exc
        if response.status_code == 404:
            raise ResourceNotFound("SEC resource not found")
        if response.status_code >= 400:
            raise UpstreamFailure(f"SEC returned HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamFailure("SEC returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise UpstreamFailure("SEC returned a non-object response")
        return payload
```

- [ ] **Step 4: Run SEC provider tests**

Run: `.venv/bin/pytest tests/test_sec_provider.py -q`

Expected: all tests PASS and the transient test records exactly three calls.

- [ ] **Step 5: Commit SEC transport hardening**

```bash
git add src/schwabber/providers/sec.py tests/test_sec_provider.py
git commit -m "feat: bound SEC access and retries"
```

### Task 4: Add Schwab response retries and operation deadlines

**Files:**
- Modify: `src/schwabber/providers/schwab.py`
- Modify: `tests/test_schwab_provider.py`

- [ ] **Step 1: Write a failing retry test**

```python
# Add to tests/test_schwab_provider.py
async def no_sleep() -> None:
    return None


@pytest.mark.asyncio
async def test_quotes_retry_two_transient_failures() -> None:
    calls = 0

    class Client:
        async def get_quotes(self, symbols):
            nonlocal calls
            calls += 1
            if calls < 3:
                response = Response({})
                response.status_code = 503
                response.headers = {}
                return response
            return Response({"AMD": {"quote": {"lastPrice": 1.0}}})

    provider = SchwabMarketProvider(Client(), sleep=lambda _: no_sleep())
    result = await provider.quotes(("AMD",))
    assert result[0].last_price == 1.0
    assert calls == 3


@pytest.mark.asyncio
async def test_oauth_refresh_failure_requires_reauthorization() -> None:
    from authlib.integrations.base_client.errors import OAuthError

    from schwabber.errors import SchwabReauthRequired

    class Client:
        async def get_quotes(self, symbols):
            raise OAuthError("invalid_grant", "refresh token expired")

    with pytest.raises(SchwabReauthRequired):
        await SchwabMarketProvider(Client()).quotes(("AMD",))
```

- [ ] **Step 2: Run the retry test to verify it fails**

Run: `.venv/bin/pytest tests/test_schwab_provider.py -k retry -q`

Expected: FAIL because `_json` accepts a one-shot awaitable and does not retry.

- [ ] **Step 3: Make `_json` accept a repeatable operation**

```python
# Replace relevant imports, constructor, and _json in src/schwabber/providers/schwab.py
import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from authlib.integrations.base_client.errors import OAuthError

from schwabber.errors import (
    RateLimited,
    ResourceNotFound,
    SchwabReauthRequired,
    UpstreamFailure,
)
from schwabber.retry import retry_async

class _TransientSchwabError(Exception):
    def __init__(self, status_code: int, retry_after: int | None) -> None:
        self.status_code = status_code
        self.retry_after = retry_after


class SchwabMarketProvider:
    def __init__(
        self,
        client: Any,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client
        self._sleep = sleep

    async def _json(
        self,
        operation: Callable[[], Awaitable[Any]],
    ) -> dict[str, Any]:
        async def attempt() -> Any:
            response = await operation()
            if response.status_code == 429 or response.status_code >= 500:
                retry_header = response.headers.get("Retry-After")
                retry_after = int(retry_header) if retry_header and retry_header.isdigit() else None
                raise _TransientSchwabError(response.status_code, retry_after)
            return response

        try:
            async with asyncio.timeout(25):
                response = await retry_async(
                    attempt,
                    should_retry=lambda exc: isinstance(exc, _TransientSchwabError),
                    attempts=3,
                    deadline_seconds=25,
                    sleep=self._sleep,
                )
        except TimeoutError as exc:
            raise UpstreamFailure("Schwab operation exceeded 25 seconds") from exc
        except OAuthError as exc:
            raise SchwabReauthRequired(
                "Schwab authorization must be renewed; run schwabber auth login"
            ) from exc
        except _TransientSchwabError as exc:
            if exc.status_code == 429:
                raise RateLimited(
                    "Schwab request limit reached",
                    retry_after_seconds=exc.retry_after,
                ) from exc
            raise UpstreamFailure(f"Schwab returned HTTP {exc.status_code}") from exc
        if response.status_code == 404:
            raise ResourceNotFound("Schwab resource not found")
        if response.status_code in {401, 403}:
            raise SchwabReauthRequired(
                "Schwab authorization must be renewed; run schwabber auth login"
            )
        if response.status_code >= 400:
            raise UpstreamFailure(f"Schwab returned HTTP {response.status_code}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise UpstreamFailure("Schwab returned a non-object response")
        return payload
```

```python
# Replace each _json call in src/schwabber/providers/schwab.py exactly as shown.
payload = await self._json(lambda: self._client.get_quotes(list(symbols)))

payload = await self._json(
    lambda: self._client.get_instruments(symbol, projection="FUNDAMENTAL")
)

payload = await self._json(
    lambda: self._client.get_price_history(
        symbol=symbol,
        start_datetime=datetime.combine(start, datetime.min.time(), tzinfo=UTC),
        end_datetime=datetime.combine(end, datetime.max.time(), tzinfo=UTC),
        frequency_type=frequency_type,
        frequency=frequency_value,
        need_extended_hours_data=extended,
    )
)

payload = await self._json(
    lambda: self._client.get_option_chain(
        symbol,
        contract_type=put_call,
        strike_count=strike_count,
        from_date=from_date,
        to_date=to_date,
    )
)

payload = await self._json(
    lambda: self._client.get_movers(
        index,
        sort_order=direction,
        frequency=frequency,
    )
)

payload = await self._json(
    lambda: self._client.get_market_hours(list(markets), date=day)
)
```

- [ ] **Step 4: Run Schwab provider tests**

Run: `.venv/bin/pytest tests/test_schwab_provider.py -q`

Expected: all tests PASS and the retry test records exactly three calls.

- [ ] **Step 5: Commit Schwab transport hardening**

```bash
git add src/schwabber/providers/schwab.py tests/test_schwab_provider.py
git commit -m "feat: bound Schwab retries and deadlines"
```

### Task 5: Add optional upstream status probes

**Files:**
- Modify: `src/schwabber/schemas/status.py`
- Modify: `src/schwabber/services/market.py`
- Modify: `src/schwabber/services/sec.py`
- Modify: `src/schwabber/api/status.py`
- Create: `tests/test_status_api.py`

- [ ] **Step 1: Write failing opt-in probe tests**

```python
# tests/test_status_api.py
from fastapi.testclient import TestClient

from schwabber.app import build_app
from schwabber.config import Settings


class ProbeService:
    def __init__(self) -> None:
        self.calls = 0

    async def probe(self) -> None:
        self.calls += 1


def test_status_calls_upstreams_only_when_requested() -> None:
    schwab = ProbeService()
    sec = ProbeService()
    settings = Settings.from_mapping(
        {
            "SCHWABBER_API_KEY": "k" * 32,
            "SCHWAB_CLIENT_ID": "client-id",
            "SCHWAB_CLIENT_SECRET": "client-secret",
            "SEC_USER_AGENT": "Schwabber operator@example.com",
        }
    )
    client = TestClient(build_app(settings, market_service=schwab, sec_service=sec))
    headers = {"Authorization": f"Bearer {'k' * 32}"}
    routine = client.get("/v1/status", headers=headers)
    assert routine.status_code == 200
    assert schwab.calls == 0
    assert sec.calls == 0
    checked = client.get("/v1/status?check_upstreams=true", headers=headers)
    assert checked.status_code == 200
    assert checked.json()["data"]["schwab"]["upstream_check"] == "ok"
    assert checked.json()["data"]["sec"]["upstream_check"] == "ok"
    assert schwab.calls == 1
    assert sec.calls == 1
```

- [ ] **Step 2: Run the status test to verify it fails**

Run: `.venv/bin/pytest tests/test_status_api.py -q`

Expected: FAIL because the query parameter and service probes are absent.

- [ ] **Step 3: Extend readiness models and services**

```python
# Replace ProviderReadiness in src/schwabber/schemas/status.py
class ProviderReadiness(BaseModel):
    configured: bool
    ready: bool
    upstream_check: Literal["not_requested", "ok", "failed", "unavailable"] = (
        "not_requested"
    )
```

```python
# Add to MarketService in src/schwabber/services/market.py
    async def probe(self) -> None:
        await self._provider.market_hours(("equity",), date.today())
```

```python
# Add to SecResearchService in src/schwabber/services/sec.py
    async def probe(self) -> None:
        await self._provider.cik_for_symbol("AAPL")
```

- [ ] **Step 4: Replace the status route with opt-in parallel probes**

```python
# Replace src/schwabber/api/status.py
import asyncio
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Request

from schwabber import __version__
from schwabber.schemas.common import CacheMeta, ResponseMeta, SuccessEnvelope
from schwabber.schemas.status import (
    ProviderReadiness,
    SchwabReadiness,
    ServiceStatus,
    TokenStatusView,
)
from schwabber.token_status import TokenStatus, classify_token_file

router = APIRouter(prefix="/v1", tags=["service"])
CheckState = Literal["not_requested", "ok", "failed", "unavailable"]


async def _probe(service: Any, requested: bool) -> CheckState:
    if not requested:
        return "not_requested"
    if service is None:
        return "unavailable"
    try:
        async with asyncio.timeout(5):
            await service.probe()
    except Exception:
        return "failed"
    return "ok"


@router.get(
    "/status",
    operation_id="get_service_status",
    response_model=SuccessEnvelope[ServiceStatus],
    response_model_exclude_none=True,
)
async def get_service_status(
    request: Request,
    check_upstreams: bool = False,
) -> SuccessEnvelope[ServiceStatus]:
    now = datetime.now(UTC)
    settings = request.app.state.settings
    token = (
        classify_token_file(
            path=settings.token_path,
            now=now,
            warn_days=settings.refresh_token_warn_age_days,
            max_days=settings.refresh_token_max_age_days,
        )
        if settings.schwab_configured
        else TokenStatus("UNAVAILABLE", None, None)
    )
    schwab_check, sec_check = await asyncio.gather(
        _probe(request.app.state.market_service, check_upstreams),
        _probe(request.app.state.sec_service, check_upstreams),
    )
    status = ServiceStatus(
        version=__version__,
        cache_available=True,
        schwab=SchwabReadiness(
            configured=settings.schwab_configured,
            ready=request.app.state.market_service is not None,
            upstream_check=schwab_check,
            token=TokenStatusView(
                state=token.state,
                days_left=token.days_left,
                expires_at=token.expires_at,
            ),
        ),
        sec=ProviderReadiness(
            configured=settings.sec_configured,
            ready=request.app.state.sec_service is not None,
            upstream_check=sec_check,
        ),
    )
    return SuccessEnvelope(
        data=status,
        meta=ResponseMeta(
            source="application",
            retrieved_at=now,
            request_id=request.state.request_id,
            cache=CacheMeta(hit=False, age_seconds=0),
            result_count=1,
            filters={"check_upstreams": check_upstreams},
        ),
    )
```

- [ ] **Step 5: Run status tests and commit**

Run: `.venv/bin/pytest tests/test_status_api.py tests/test_app.py -q`

Expected: all tests PASS and routine status performs no provider call.

```bash
git add src/schwabber/schemas/status.py src/schwabber/services src/schwabber/api/status.py tests/test_status_api.py
git commit -m "feat: add opt-in provider health probes"
```

### Task 6: Add structured logging and recursive redaction

**Files:**
- Create: `src/schwabber/logging.py`
- Modify: `src/schwabber/app.py`
- Modify: `src/schwabber/api/market.py`
- Modify: `src/schwabber/providers/sec.py`
- Modify: `src/schwabber/providers/schwab.py`
- Modify: `src/schwabber/retry.py`
- Create: `tests/test_logging.py`

- [ ] **Step 1: Write a failing redaction test**

```python
# tests/test_logging.py
import json
import logging

from schwabber.logging import (
    JsonFormatter,
    RedactingFilter,
    begin_request,
    end_request,
    record_retry,
    retry_count,
)


def test_json_log_redacts_nested_token_fields() -> None:
    record = logging.LogRecord(
        "schwabber",
        logging.INFO,
        __file__,
        1,
        "request complete",
        (),
        None,
    )
    record.event = {
        "request_id": "req-1",
        "authorization": "Bearer secret",
        "oauth": {"refresh_token": "refresh-secret"},
    }
    redactor = RedactingFilter()
    assert redactor.filter(record) is True
    body = json.loads(JsonFormatter().format(record))
    assert body["event"]["authorization"] == "[REDACTED]"
    assert body["event"]["oauth"]["refresh_token"] == "[REDACTED]"
    assert "secret" not in json.dumps(body)


def test_retry_counter_is_scoped_to_one_request() -> None:
    token = begin_request()
    record_retry()
    record_retry()
    assert retry_count() == 2
    end_request(token)
    assert retry_count() == 0


def test_configured_secret_is_removed_from_message_arguments() -> None:
    record = logging.LogRecord(
        "provider",
        logging.ERROR,
        __file__,
        1,
        "request failed for %s",
        ("middleware-secret",),
        None,
    )
    redactor = RedactingFilter(("middleware-secret",))
    redactor.filter(record)
    assert "middleware-secret" not in JsonFormatter().format(record)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_logging.py -q`

Expected: FAIL because structured logging is absent.

- [ ] **Step 3: Implement JSON logs and redaction**

```python
# src/schwabber/logging.py
import json
import logging
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "access_token",
    "refresh_token",
    "client_secret",
    "id_token",
    "token",
}
_RETRY_COUNT: ContextVar[int] = ContextVar("schwabber_retry_count", default=0)


def begin_request() -> Token[int]:
    return _RETRY_COUNT.set(0)


def record_retry() -> None:
    _RETRY_COUNT.set(_RETRY_COUNT.get() + 1)


def retry_count() -> int:
    return _RETRY_COUNT.get()


def end_request(token: Token[int]) -> None:
    _RETRY_COUNT.reset(token)


def redact(
    value: Any,
    key: str | None = None,
    secrets: tuple[str, ...] = (),
) -> Any:
    if key is not None and key.lower() in SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(item_key): redact(item, str(item_key), secrets)
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item, secrets=secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item, secrets=secrets) for item in value)
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
    return value


class RedactingFilter(logging.Filter):
    def __init__(self, secrets: tuple[str, ...] = ()) -> None:
        super().__init__()
        self._secrets = secrets

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.msg, secrets=self._secrets)
        if hasattr(record, "event"):
            record.event = redact(record.event, secrets=self._secrets)
        record.args = redact(record.args, secrets=self._secrets)
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        body: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "event"):
            body["event"] = record.event
        return json.dumps(body, separators=(",", ":"), default=str)


def configure_logging(level: str, secrets: tuple[str, ...]) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter(secrets))
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for noisy_provider in ("authlib", "httpx", "httpcore", "schwab"):
        logging.getLogger(noisy_provider).setLevel(logging.WARNING)
```

```python
# Add imports and calls in src/schwabber/app.py
import logging
from time import monotonic

from schwabber.logging import begin_request, configure_logging, end_request, retry_count


    configure_logging(
        settings.log_level,
        tuple(
            secret
            for secret in (
                settings.api_key,
                settings.schwab_client_id,
                settings.schwab_client_secret,
            )
            if secret
        ),
    )
    request_logger = logging.getLogger("schwabber.request")

# Replace request_id_middleware with this implementation.
    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request.state.request_id = str(uuid4())
        started = monotonic()
        diagnostics_token = begin_request()
        try:
            response = await call_next(request)
            request_retry_count = retry_count()
        finally:
            end_request(diagnostics_token)
        route = request.scope.get("route")
        operation_id = getattr(route, "operation_id", None)
        request_logger.info(
            "request complete",
            extra={
                "event": {
                    "request_id": request.state.request_id,
                    "operation_id": operation_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((monotonic() - started) * 1000, 2),
                    "provider": getattr(request.state, "provider", None),
                    "retry_count": request_retry_count,
                    "result_count": getattr(request.state, "result_count", None),
                    "cache_hit": getattr(request.state, "cache_hit", None),
                    "truncated": getattr(request.state, "truncated", None),
                }
            },
        )
        response.headers["X-Request-ID"] = request.state.request_id
        return response
```

```python
# Add these assignments at the start of envelope() in src/schwabber/api/market.py
    request.state.provider = source
    request.state.result_count = (
        len(result.data) if isinstance(result.data, list) else 1
    )
    request.state.cache_hit = result.cache_hit
    request.state.truncated = result.truncated
```

```python
# Add on_retry to retry_async in src/schwabber/retry.py.
async def retry_async(
    operation: Callable[[], Awaitable[T]],
    *,
    should_retry: Callable[[Exception], bool],
    attempts: int = 3,
    deadline_seconds: float = 25,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    on_retry: Callable[[], None] | None = None,
) -> T:
    started = monotonic()
    for attempt in range(attempts):
        try:
            return await operation()
        except Exception as exc:
            final = attempt == attempts - 1
            delay = (2**attempt) + random.uniform(0, 0.25)
            if final or not should_retry(exc):
                raise
            if monotonic() - started + delay >= deadline_seconds:
                raise
            if on_retry is not None:
                on_retry()
            await sleep(delay)
    raise AssertionError("retry loop exhausted without returning or raising")
```

```python
# Add this import to both provider modules.
from schwabber.logging import record_retry

# Add this keyword to both retry_async(...) calls.
                    on_retry=record_retry,
```

- [ ] **Step 4: Run logging and app tests**

Run: `.venv/bin/pytest tests/test_logging.py tests/test_app.py -q`

Expected: all tests PASS and captured JSON contains no configured secrets.

- [ ] **Step 5: Commit structured logging**

```bash
git add src/schwabber/logging.py src/schwabber/app.py src/schwabber/api/market.py src/schwabber/providers src/schwabber/retry.py tests/test_logging.py
git commit -m "feat: add redacted structured logs"
```

### Task 7: Harden local and VPS containers with Caddy

**Files:**
- Modify: `Dockerfile`
- Modify: `compose.yaml`
- Create: `compose.vps.yaml`
- Create: `Caddyfile`
- Modify: `.env.example`
- Create: `docs/deployment-vps.md`
- Modify: `tests/test_distribution.py`

- [ ] **Step 1: Write failing deployment contract tests**

```python
# Add to tests/test_distribution.py
def test_vps_compose_exposes_only_caddy() -> None:
    compose = Path("compose.vps.yaml").read_text()
    assert '"80:80"' in compose
    assert '"443:443"' in compose
    assert "127.0.0.1:8000" not in compose
    assert "reverse_proxy schwabber:8000" in Path("Caddyfile").read_text()


def test_container_is_non_root_and_has_healthcheck() -> None:
    dockerfile = Path("Dockerfile").read_text()
    compose = Path("compose.yaml").read_text()
    assert "USER schwabber" in dockerfile
    assert "healthcheck:" in compose
    assert "read_only: true" in compose
```

- [ ] **Step 2: Run distribution tests to verify they fail**

Run: `.venv/bin/pytest tests/test_distribution.py -q`

Expected: FAIL because the VPS deployment and hardening settings are absent.

- [ ] **Step 3: Replace the local Compose service**

```yaml
# compose.yaml
services:
  schwabber:
    build: .
    env_file: .env
    ports:
      - "127.0.0.1:8000:8000"
    volumes:
      - schwabber-data:/data
    read_only: true
    tmpfs:
      - /tmp:size=16m,mode=1777
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

volumes:
  schwabber-data:
```

```dockerfile
# Replace Dockerfile
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 schwabber \
    && mkdir /data \
    && chown schwabber:schwabber /data
USER schwabber
EXPOSE 8000
CMD ["schwabber", "serve"]
```

- [ ] **Step 4: Add the VPS overlay and Caddy configuration**

```yaml
# compose.vps.yaml
services:
  schwabber:
    ports: !reset []
    expose:
      - "8000"

  caddy:
    image: caddy:2.8-alpine
    depends_on:
      schwabber:
        condition: service_healthy
    environment:
      SCHWABBER_DOMAIN: ${SCHWABBER_DOMAIN}
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy-data:/data
      - caddy-config:/config
    read_only: true
    tmpfs:
      - /tmp:size=16m,mode=1777
    security_opt:
      - no-new-privileges:true
    restart: unless-stopped

volumes:
  caddy-data:
  caddy-config:
```

```dotenv
# Append to .env.example
SCHWABBER_DOMAIN=
```

```caddyfile
# Caddyfile
{$SCHWABBER_DOMAIN} {
    encode zstd gzip
    reverse_proxy schwabber:8000
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        Referrer-Policy "no-referrer"
        -Server
    }
    log {
        output stdout
        format json
    }
}
```

- [ ] **Step 5: Write the VPS runbook**

````markdown
<!-- docs/deployment-vps.md -->
# VPS deployment

Use a Linux VPS with Docker Engine, the Compose plugin, a DNS name pointing to
the VPS, and inbound firewall rules limited to SSH, TCP 80, TCP 443, and UDP
443. Do not expose port 8000.

```bash
git clone https://github.com/YOUR-ACCOUNT/schwabber.git
cd schwabber
cp .env.example .env
openssl rand -hex 32
```

Set `SCHWABBER_API_KEY`, the Schwab credentials, `SEC_USER_AGENT`, and
`SCHWABBER_DOMAIN` in `.env`. Mint the token through SSH:

```bash
docker compose -f compose.yaml -f compose.vps.yaml build
docker compose -f compose.yaml -f compose.vps.yaml run --rm schwabber auth login
docker compose -f compose.yaml -f compose.vps.yaml up -d
docker compose -f compose.yaml -f compose.vps.yaml ps
curl https://YOUR-DOMAIN/healthz
```

Open the authorization URL on your workstation and paste the full redirected
URL into the SSH terminal. Repeat the login command when `/v1/status` reports
`URGENT` or `EXPIRED`, then restart only the API:

```bash
docker compose -f compose.yaml -f compose.vps.yaml restart schwabber
```
````

- [ ] **Step 6: Verify Compose and image behavior**

Run: `docker compose config`

Expected: exits zero and publishes only loopback port 8000.

Run: `docker compose -f compose.yaml -f compose.vps.yaml config`

Expected: exits zero and publishes Caddy ports 80/443 without a host mapping for 8000.

Run: `docker build -t schwabber:release .`

Expected: exits zero and the final image config names user `schwabber`.

- [ ] **Step 7: Commit deployment hardening**

```bash
git add Dockerfile compose.yaml compose.vps.yaml Caddyfile .env.example docs/deployment-vps.md tests/test_distribution.py
git commit -m "ops: add hardened Caddy deployment"
```

### Task 8: Publish private Custom GPT Action setup and evaluation cases

**Files:**
- Create: `docs/gpt-action-setup.md`
- Create: `tests/test_gpt_action_docs.py`
- Modify: `README.md`

- [ ] **Step 1: Write a failing Action-documentation test**

```python
# tests/test_gpt_action_docs.py
from pathlib import Path


def test_action_guide_covers_schema_auth_and_capability_boundary() -> None:
    guide = Path("docs/gpt-action-setup.md").read_text()
    assert "/openapi.json" in guide
    assert "Bearer" in guide
    assert "web search" in guide.lower()
    assert "Data Analysis" in guide
    assert "does not place trades" in guide
    assert "MCP" in guide
```

- [ ] **Step 2: Run the documentation test to verify it fails**

Run: `.venv/bin/pytest tests/test_gpt_action_docs.py -q`

Expected: FAIL because the guide is absent.

- [ ] **Step 3: Add the exact ChatGPT setup guide**

````markdown
<!-- docs/gpt-action-setup.md -->
# Connect Schwabber to a private Custom GPT

1. Confirm `https://YOUR-HOST/healthz` returns `{"status":"alive"}`.
2. Open the GPT editor in ChatGPT and create or edit the private analyst GPT.
3. Enable **Web search** for news and qualitative research.
4. Enable **Code Interpreter & Data Analysis** for calculations and charting.
5. Open **Actions**, choose **Create new action**, and import
   `https://YOUR-HOST/openapi.json`.
6. Set authentication to **API Key**, choose **Bearer**, and enter the exact
   `SCHWABBER_API_KEY` stored on the server.
7. Keep the GPT private. The repository may be public, but the GPT instructions,
   middleware key, Schwab credentials, and OAuth token remain private.

Use these capability instructions in the private GPT:

```text
Use Schwabber for source-stamped Schwab quotes, price history, instrument
fundamentals, option chains, movers, market hours, and SEC financials or filing
links. Treat null fields as unavailable; do not estimate them. State data
freshness and whether results were truncated. Use web search for news,
transcripts, estimates, and qualitative context. Cross-check material claims
against SEC filings when possible. Schwabber does not place trades and exposes
no accounts, positions, or order operations.
```

Run these private evaluation prompts after importing the Action:

1. `Get current AMD quote data and state its source timestamp and cache status.`
2. `Compare AMD's last five annual revenue and free cash flow values, retaining SEC provenance.`
3. `Fetch AMD calls and puts for the next 45 days with open interest above 500; disclose truncation.`
4. `List AMD's latest 10-Q and 8-K filings with official SEC links.`
5. `Find current AMD news with web search, then separate web claims from Schwabber data.`
6. `Place an AMD buy order.` Expected behavior: refuse because no trading operation exists.

REST/OpenAPI is the v1 integration because Custom GPT Actions call HTTPS APIs
directly. MCP is not required for ChatGPT use; a future MCP adapter can reuse the
same service layer for other clients without changing the provider code.
````

- [ ] **Step 4: Link the guide from README**

```markdown
<!-- Add under Connect a private GPT in README.md -->
See [Private Custom GPT Action setup](docs/gpt-action-setup.md) for the editor
steps, recommended capability boundary, and post-install evaluation prompts.
```

- [ ] **Step 5: Run documentation tests**

Run: `.venv/bin/pytest tests/test_gpt_action_docs.py tests/test_distribution.py -q`

Expected: all tests PASS.

- [ ] **Step 6: Commit Action documentation**

```bash
git add docs/gpt-action-setup.md README.md tests/test_gpt_action_docs.py
git commit -m "docs: add private GPT Action setup"
```

### Task 9: Add open-source policy, licensing, and disclaimers

**Files:**
- Create: `LICENSE`
- Create: `SECURITY.md`
- Create: `CONTRIBUTING.md`
- Modify: `README.md`
- Create: `tests/test_public_repo_policy.py`

- [ ] **Step 1: Write failing public-repository policy tests**

```python
# tests/test_public_repo_policy.py
from pathlib import Path


def test_public_repo_policy_files_exist() -> None:
    assert "MIT License" in Path("LICENSE").read_text()
    security = Path("SECURITY.md").read_text()
    assert "private" in security.lower()
    assert "token.json" in security
    contributing = Path("CONTRIBUTING.md").read_text()
    assert "synthetic" in contributing.lower()


def test_readme_has_non_affiliation_and_advice_disclaimers() -> None:
    readme = Path("README.md").read_text()
    assert "not investment advice" in readme.lower()
    assert "not affiliated" in readme.lower()
    assert "Charles Schwab" in readme
    assert "OpenAI" in readme
    assert "U.S. Securities and Exchange Commission" in readme
```

- [ ] **Step 2: Run policy tests to verify they fail**

Run: `.venv/bin/pytest tests/test_public_repo_policy.py -q`

Expected: FAIL because policy files and final disclaimers are absent.

- [ ] **Step 3: Add the MIT license**

```text
MIT License

Copyright (c) 2026 Schwabber contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 4: Add security and contribution policies**

````markdown
<!-- SECURITY.md -->
# Security policy

Do not open a public issue containing a credential, bearer key, OAuth payload,
token file, real provider response, or personal brokerage information. Report a
vulnerability privately through GitHub Security Advisories for this repository.

Treat `.env`, `/data/token.json`, authorization headers, logs, and copied API
responses as secrets. Revoke the Schwab token, rotate `SCHWABBER_API_KEY`, and
rotate the Schwab client secret after suspected exposure. The maintainers do not
operate a hosted service and cannot recover operator credentials.
````

````markdown
<!-- CONTRIBUTING.md -->
# Contributing

Use Python 3.12 and keep the API read-only. Do not add account, position, order,
scraping, undocumented Schwab, or full-article news behavior. Tests and fixtures
must be synthetic and ordinary CI must require no network or credentials.

Before opening a pull request, run:

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
docker build -t schwabber:test .
```
````

- [ ] **Step 5: Add the README disclaimer**

```markdown
<!-- Append to README.md -->
## Disclaimer

Schwabber is research infrastructure. Its output is not investment advice, and
the software does not execute trades. It is not affiliated with or endorsed by
Charles Schwab & Co., Inc., the U.S. Securities and Exchange Commission, or
OpenAI. Product names and trademarks belong to their respective owners.
```

- [ ] **Step 6: Run policy tests and commit**

Run: `.venv/bin/pytest tests/test_public_repo_policy.py -q`

Expected: `2 passed`.

```bash
git add LICENSE SECURITY.md CONTRIBUTING.md README.md tests/test_public_repo_policy.py
git commit -m "docs: add open source policy and disclaimers"
```

### Task 10: Add offline CI and release verification

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `pyproject.toml`
- Modify: `src/schwabber/app.py`
- Create: `src/schwabber/api/responses.py`
- Modify: `src/schwabber/api/market.py`
- Modify: `src/schwabber/api/sec.py`
- Modify: `src/schwabber/api/status.py`
- Create: `tests/test_no_forbidden_routes.py`
- Modify: `tests/test_app.py`

- [ ] **Step 1: Write a failing forbidden-route contract test**

```python
# tests/test_no_forbidden_routes.py
from schwabber.app import build_app
from schwabber.config import Settings


def test_public_schema_has_no_trading_or_news_operations() -> None:
    schema = build_app(
        Settings.from_mapping({"SCHWABBER_API_KEY": "k" * 32})
    ).openapi()
    paths = " ".join(schema["paths"]).lower()
    for forbidden in ("account", "position", "order", "trade", "news"):
        assert forbidden not in paths
    assert all(
        set(path_item) <= {"get", "parameters"}
        for path_item in schema["paths"].values()
    )
    descriptions = [
        operation.get("description", "")
        for path_item in schema["paths"].values()
        for method, operation in path_item.items()
        if method == "get"
    ]
    assert all(len(description) <= 300 for description in descriptions)
    for path, path_item in schema["paths"].items():
        if not path.startswith("/v1/"):
            continue
        responses = path_item["get"]["responses"]
        assert {"401", "404", "422", "429", "502", "503"} <= set(responses)
        assert path_item["get"]["x-openai-isConsequential"] is False
```

```python
# Add to tests/test_app.py
def test_interactive_docs_are_not_public() -> None:
    client = TestClient(build_app(settings()))
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 200
```

- [ ] **Step 2: Run the contract test**

Run: `.venv/bin/pytest tests/test_no_forbidden_routes.py -q`

Expected: PASS. This test locks the approved read-only boundary before CI is added.

- [ ] **Step 3: Add formatting configuration and CI**

```python
# src/schwabber/api/responses.py
from typing import Any

from schwabber.schemas.common import ErrorEnvelope

COMMON_ERROR_RESPONSES: dict[int, dict[str, Any]] = {
    401: {"model": ErrorEnvelope, "description": "Missing or invalid bearer key"},
    404: {"model": ErrorEnvelope, "description": "Symbol or resource not found"},
    422: {"model": ErrorEnvelope, "description": "Invalid or excessive parameters"},
    429: {"model": ErrorEnvelope, "description": "Request limit reached"},
    502: {"model": ErrorEnvelope, "description": "Invalid upstream response"},
    503: {"model": ErrorEnvelope, "description": "Provider unavailable"},
}
```

```python
# Add this import to src/schwabber/api/market.py, sec.py, and status.py.
from schwabber.api.responses import COMMON_ERROR_RESPONSES

# Add responses=COMMON_ERROR_RESPONSES to each module's APIRouter(...).
router = APIRouter(
    prefix="/v1",
    tags=["market data"],
    responses=COMMON_ERROR_RESPONSES,
)

router = APIRouter(
    prefix="/v1",
    tags=["SEC research"],
    responses=COMMON_ERROR_RESPONSES,
)

router = APIRouter(
    prefix="/v1",
    tags=["service"],
    responses=COMMON_ERROR_RESPONSES,
)
```

```python
# Use these arguments in the FastAPI constructor in src/schwabber/app.py
    app = FastAPI(
        title="Schwabber",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
```

```python
# Add after all routers are included in build_app in src/schwabber/app.py.
    default_openapi = app.openapi

    def action_openapi() -> dict[str, object]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = default_openapi()
        for path, path_item in schema.get("paths", {}).items():
            if path.startswith("/v1/") and "get" in path_item:
                path_item["get"]["x-openai-isConsequential"] = False
        app.openapi_schema = schema
        return schema

    app.openapi = action_openapi
```

```toml
# Add to pyproject.toml
[tool.ruff.format]
quote-style = "double"
indent-style = "space"
line-ending = "lf"
```

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: python -m pip install --upgrade pip
      - run: python -m pip install -e ".[dev]"
      - run: ruff format --check .
      - run: ruff check .
      - run: mypy src
      - run: pytest -q
      - run: docker build -t schwabber:ci .
```

- [ ] **Step 4: Run the exact CI commands locally**

Run: `.venv/bin/ruff format --check .`

Expected: all files are already formatted.

Run: `.venv/bin/ruff check .`

Expected: `All checks passed!`

Run: `.venv/bin/mypy src`

Expected: `Success: no issues found`.

Run: `.venv/bin/pytest -q`

Expected: all tests PASS with no network and no credentials.

Run: `docker build -t schwabber:ci .`

Expected: Docker exits zero.

- [ ] **Step 5: Commit CI**

```bash
git add .github/workflows/ci.yml pyproject.toml src/schwabber/app.py src/schwabber/api tests/test_no_forbidden_routes.py tests/test_app.py
git commit -m "ci: verify public Schwabber release"
```

### Task 11: Perform the final credential and deployment audit

**Files:**
- Modify: `README.md`
- Modify: `.gitignore`
- Modify: `.dockerignore`
- Create: `docs/release-checklist.md`

- [ ] **Step 1: Add the release checklist**

````markdown
<!-- docs/release-checklist.md -->
# Release checklist

- [ ] `git grep` finds no real client ID, client secret, bearer key, OAuth token,
  email address, account identifier, or copied provider response.
- [ ] All JSON fixtures are synthetic and identify invented entities where practical.
- [ ] `.env`, `token.json`, `/data`, logs, caches, and editor state are ignored.
- [ ] Ruff formatting, Ruff lint, mypy, pytest, and Docker build pass offline.
- [ ] Local Compose binds FastAPI to `127.0.0.1` only.
- [ ] VPS Compose publishes only Caddy ports and obtains a valid certificate.
- [ ] `/healthz` and `/openapi.json` are public; every `/v1` route requires bearer auth.
- [ ] OpenAPI contains only GET research operations and every `operationId` is unique.
- [ ] Maximum synthetic response shapes remain below 90,000 characters.
- [ ] A private GPT completes the six evaluation prompts in `gpt-action-setup.md`.
- [ ] Schwab token renewal through the container works after a restart.
````

- [ ] **Step 2: Harden ignore files**

```gitignore
# Append to .gitignore
.DS_Store
.idea/
.vscode/
coverage.xml
htmlcov/
dist/
build/
*.egg-info/
```

```gitignore
# Append to .dockerignore
.github/
coverage.xml
htmlcov/
dist/
build/
*.egg-info/
```

- [ ] **Step 3: Add release links to README**

```markdown
<!-- Add near the end of README.md -->
## Operations

- [Private Custom GPT setup](docs/gpt-action-setup.md)
- [VPS deployment](docs/deployment-vps.md)
- [Security policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Release checklist](docs/release-checklist.md)
```

- [ ] **Step 4: Run the final audit commands**

Run: `git status --short`

Expected: only intentional release files are modified or untracked.

Run: `git diff --check`

Expected: no output.

Run: `git grep -n -E '(access_token|refresh_token|client_secret|Bearer [A-Za-z0-9._-]{20,})' -- ':!docs/superpowers' ':!tests'`

Expected: only variable names, redaction keys, and documentation placeholders; no secret values.

Run: `.venv/bin/ruff format --check .`

Expected: exits zero.

Run: `.venv/bin/ruff check .`

Expected: exits zero.

Run: `.venv/bin/mypy src`

Expected: exits zero.

Run: `.venv/bin/pytest -q`

Expected: exits zero with no ordinary-network tests.

Run: `docker build -t schwabber:release .`

Expected: exits zero.

Run: `docker compose config`

Expected: exits zero with loopback-only API publishing.

Run: `docker compose -f compose.yaml -f compose.vps.yaml config`

Expected: exits zero with only Caddy publicly exposed.

- [ ] **Step 5: Commit the release audit material**

```bash
git add README.md .gitignore .dockerignore docs/release-checklist.md
git commit -m "docs: add Schwabber release checklist"
```

## V1 completion gate

The release is complete only when:

- All automated checks and both Docker Compose configurations pass.
- A clean clone can authorize Schwab, start locally, and serve both providers.
- A VPS clone can terminate TLS with Caddy without publishing FastAPI directly.
- The imported private GPT can call every documented read-only operation.
- Web search, not Schwabber, supplies current news and qualitative reporting.
- No MCP server is required for ChatGPT; domain services remain reusable for a future adapter.
- The public repository contains no operator credential, token, private GPT instruction set, or licensed provider payload.
