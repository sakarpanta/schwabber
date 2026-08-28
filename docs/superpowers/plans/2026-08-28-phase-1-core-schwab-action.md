# Phase 1: Core Schwab GPT Action Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a locally runnable, authenticated FastAPI GPT Action that exposes bounded, normalized, read-only Schwab quotes, history, instruments, options, movers, market hours, and token status.

**Architecture:** FastAPI routes call a protocol-neutral `MarketService`; only `providers/schwab.py` imports `schwab-py`. A single async Schwab client owns token refresh, while service-level caches add freshness metadata without leaking raw provider payloads.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic, httpx, schwab-py, uvicorn, pytest, pytest-asyncio, Ruff, mypy, Docker Compose

---

## File map

- `pyproject.toml`: package metadata, runtime dependencies, test/lint/type-check configuration.
- `src/schwabber/config.py`: environment parsing and secret-safe validation.
- `src/schwabber/errors.py`: typed application errors and HTTP mappings.
- `src/schwabber/schemas/common.py`: success/error envelopes and provider metadata.
- `src/schwabber/schemas/market.py`: normalized Schwab response models.
- `src/schwabber/auth.py`: bearer-key verification.
- `src/schwabber/cache.py`: bounded TTL/LRU cache.
- `src/schwabber/retry.py`: deadline-aware async retry helper.
- `src/schwabber/token_status.py`: refresh-token age classification.
- `src/schwabber/providers/base.py`: provider protocol consumed by the service.
- `src/schwabber/providers/schwab.py`: the only module that calls `schwab-py`.
- `src/schwabber/services/market.py`: cache, collection bounds, and source metadata.
- `src/schwabber/api/dependencies.py`: request dependencies for settings and services.
- `src/schwabber/api/market.py`: protected market-data routes.
- `src/schwabber/api/status.py`: protected readiness/token route.
- `src/schwabber/app.py`: application factory, lifespan, middleware, and error handlers.
- `src/schwabber/cli.py`: `serve`, `auth login`, and read-only `smoke` commands.
- `tests/`: synthetic, offline unit and contract tests.
- `Dockerfile`, `compose.yaml`, `.env.example`, `.gitignore`: local Docker-first operation.

### Task 1: Scaffold the Python package and quality gates

**Files:**
- Create: `pyproject.toml`
- Create: `src/schwabber/__init__.py`
- Create: `tests/test_package.py`
- Create: `.gitignore`

- [ ] **Step 1: Write the failing package test**

```python
# tests/test_package.py
import schwabber


def test_package_has_version() -> None:
    assert schwabber.__version__ == "0.1.0"
```

- [ ] **Step 2: Run the test to verify the package is absent**

Run: `python3.12 -m pytest tests/test_package.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'schwabber'`.

- [ ] **Step 3: Add package metadata and the minimal module**

```toml
# pyproject.toml
[project]
name = "schwabber"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "authlib>=1.3",
  "fastapi>=0.115",
  "httpx>=0.27",
  "pydantic>=2.9",
  "schwab-py>=1.5",
  "uvicorn[standard]>=0.30",
]

[project.optional-dependencies]
dev = [
  "mypy>=1.11",
  "pytest>=8",
  "pytest-asyncio>=0.24",
  "ruff>=0.7",
]

[project.scripts]
schwabber = "schwabber.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/schwabber"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 88
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.ruff.lint.flake8-bugbear]
extend-immutable-calls = ["fastapi.Depends", "fastapi.Path", "fastapi.Query"]

[tool.mypy]
python_version = "3.12"
packages = ["schwabber"]
no_implicit_optional = true
warn_return_any = true
warn_unused_configs = true
warn_unused_ignores = true
```

```python
# src/schwabber/__init__.py
__version__ = "0.1.0"
```

```gitignore
# .gitignore
.env
.venv/
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
data/
token.json
*.log
```

- [ ] **Step 4: Install and verify the scaffold**

Run: `python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pytest tests/test_package.py -q`

Expected: `1 passed`.

- [ ] **Step 5: Commit the scaffold**

```bash
git add pyproject.toml src/schwabber/__init__.py tests/test_package.py .gitignore
git commit -m "build: scaffold schwabber package"
```

### Task 2: Add configuration with degraded-provider support

**Files:**
- Create: `src/schwabber/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing configuration tests**

```python
# tests/test_config.py
import pytest

from schwabber.config import ConfigurationError, Settings


def test_settings_require_a_long_middleware_key() -> None:
    with pytest.raises(ConfigurationError, match="at least 32"):
        Settings.from_mapping({"SCHWABBER_API_KEY": "short"})


def test_missing_schwab_values_create_degraded_configuration() -> None:
    settings = Settings.from_mapping({"SCHWABBER_API_KEY": "x" * 32})
    assert settings.schwab_configured is False
    assert settings.token_path.as_posix() == "/data/token.json"


def test_schwab_is_configured_only_with_id_and_secret() -> None:
    settings = Settings.from_mapping(
        {
            "SCHWABBER_API_KEY": "x" * 32,
            "SCHWAB_CLIENT_ID": "client",
            "SCHWAB_CLIENT_SECRET": "secret",
        }
    )
    assert settings.schwab_configured is True


def test_configuration_error_does_not_echo_secret_value() -> None:
    supplied = "operator-secret"
    with pytest.raises(ConfigurationError) as captured:
        Settings.from_mapping({"SCHWABBER_API_KEY": supplied})
    assert supplied not in str(captured.value)


def test_numeric_limits_are_validated_at_startup() -> None:
    with pytest.raises(ConfigurationError, match="REQUESTS_PER_MINUTE"):
        Settings.from_mapping(
            {
                "SCHWABBER_API_KEY": "k" * 32,
                "SCHWABBER_REQUESTS_PER_MINUTE": "0",
            }
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_config.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'schwabber.config'`.

- [ ] **Step 3: Implement immutable settings**

```python
# src/schwabber/config.py
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    api_key: str
    schwab_client_id: str | None
    schwab_client_secret: str | None
    callback_url: str
    token_path: Path
    refresh_token_max_age_days: int
    refresh_token_warn_age_days: int
    requests_per_minute: int
    log_level: str

    @property
    def schwab_configured(self) -> bool:
        return bool(self.schwab_client_id and self.schwab_client_secret)

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> "Settings":
        api_key = values.get("SCHWABBER_API_KEY", "")
        if len(api_key) < 32:
            raise ConfigurationError("SCHWABBER_API_KEY must be at least 32 characters")
        try:
            max_age = int(values.get("SCHWAB_REFRESH_TOKEN_MAX_AGE_DAYS", "7"))
            warn_age = int(values.get("SCHWAB_REFRESH_TOKEN_WARN_AGE_DAYS", "6"))
            requests_per_minute = int(
                values.get("SCHWABBER_REQUESTS_PER_MINUTE", "60")
            )
        except ValueError as exc:
            raise ConfigurationError("Numeric configuration values must be integers") from exc
        if max_age <= 0 or not 0 <= warn_age < max_age:
            raise ConfigurationError(
                "Schwab token warning age must be below its positive maximum age"
            )
        if requests_per_minute <= 0:
            raise ConfigurationError("SCHWABBER_REQUESTS_PER_MINUTE must be positive")
        return cls(
            api_key=api_key,
            schwab_client_id=values.get("SCHWAB_CLIENT_ID") or None,
            schwab_client_secret=values.get("SCHWAB_CLIENT_SECRET") or None,
            callback_url=values.get(
                "SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182"
            ),
            token_path=Path(values.get("SCHWAB_TOKEN_PATH", "/data/token.json")),
            refresh_token_max_age_days=max_age,
            refresh_token_warn_age_days=warn_age,
            requests_per_minute=requests_per_minute,
            log_level=values.get("SCHWABBER_LOG_LEVEL", "INFO"),
        )

    @classmethod
    def from_env(cls) -> "Settings":
        return cls.from_mapping(os.environ)
```

- [ ] **Step 4: Run configuration tests**

Run: `.venv/bin/pytest tests/test_config.py -q`

Expected: `5 passed`.

- [ ] **Step 5: Commit configuration**

```bash
git add src/schwabber/config.py tests/test_config.py
git commit -m "feat: add secret-safe configuration"
```

### Task 3: Define common envelopes and typed errors

**Files:**
- Create: `src/schwabber/schemas/__init__.py`
- Create: `src/schwabber/schemas/common.py`
- Create: `src/schwabber/errors.py`
- Create: `tests/test_common_schemas.py`

- [ ] **Step 1: Write the failing envelope test**

```python
# tests/test_common_schemas.py
from datetime import UTC, datetime

from schwabber.schemas.common import CacheMeta, ResponseMeta, SuccessEnvelope


def test_success_envelope_serializes_freshness_metadata() -> None:
    envelope = SuccessEnvelope[dict[str, int]](
        data={"count": 1},
        meta=ResponseMeta(
            source="schwab",
            retrieved_at=datetime(2026, 8, 28, tzinfo=UTC),
            request_id="req-1",
            cache=CacheMeta(hit=False, age_seconds=0),
            result_count=1,
            truncated=False,
        ),
    )
    body = envelope.model_dump(mode="json")
    assert body["meta"]["source"] == "schwab"
    assert body["meta"]["cache"] == {"hit": False, "age_seconds": 0}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_common_schemas.py -q`

Expected: FAIL because `schwabber.schemas.common` does not exist.

- [ ] **Step 3: Implement envelopes and error taxonomy**

```python
# src/schwabber/schemas/common.py
from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class CacheMeta(BaseModel):
    hit: bool
    age_seconds: int


class ResponseMeta(BaseModel):
    source: Literal["schwab", "sec", "application"]
    retrieved_at: datetime
    request_id: str
    cache: CacheMeta
    result_count: int | None = None
    truncated: bool = False
    filters: dict[str, str | int | bool] | None = None


class SuccessEnvelope(BaseModel, Generic[T]):
    data: T
    meta: ResponseMeta


class ErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool
    retry_after_seconds: int | None
    request_id: str


class ErrorEnvelope(BaseModel):
    error: ErrorDetail
```

```python
# src/schwabber/errors.py
class AppError(Exception):
    status_code = 500
    code = "INTERNAL_ERROR"
    retryable = False

    def __init__(self, message: str, retry_after_seconds: int | None = None):
        super().__init__(message)
        self.message = message
        self.retry_after_seconds = retry_after_seconds


class Unauthorized(AppError):
    status_code = 401
    code = "UNAUTHORIZED"


class InvalidRequest(AppError):
    status_code = 422
    code = "INVALID_REQUEST"


class ResourceNotFound(AppError):
    status_code = 404
    code = "RESOURCE_NOT_FOUND"


class ProviderUnavailable(AppError):
    status_code = 503
    code = "PROVIDER_UNAVAILABLE"


class SchwabReauthRequired(ProviderUnavailable):
    code = "SCHWAB_REAUTH_REQUIRED"


class UpstreamFailure(AppError):
    status_code = 502
    code = "UPSTREAM_FAILURE"
    retryable = True


class RateLimited(AppError):
    status_code = 429
    code = "RATE_LIMITED"
    retryable = True
```

```python
# src/schwabber/schemas/__init__.py
"""Public response schemas."""
```

- [ ] **Step 4: Run schema tests**

Run: `.venv/bin/pytest tests/test_common_schemas.py -q`

Expected: `1 passed`.

- [ ] **Step 5: Commit schemas**

```bash
git add src/schwabber/schemas src/schwabber/errors.py tests/test_common_schemas.py
git commit -m "feat: define API envelopes and errors"
```

### Task 4: Build authentication and the application skeleton

**Files:**
- Create: `src/schwabber/auth.py`
- Create: `src/schwabber/app.py`
- Create: `tests/test_app.py`

- [ ] **Step 1: Write failing route and authentication tests**

```python
# tests/test_app.py
from fastapi.testclient import TestClient

from schwabber.app import build_app
from schwabber.config import Settings


def settings() -> Settings:
    return Settings.from_mapping({"SCHWABBER_API_KEY": "k" * 32})


def test_health_is_public_and_reveals_only_liveness() -> None:
    response = TestClient(build_app(settings())).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_v1_route_requires_bearer_key() -> None:
    client = TestClient(build_app(settings()))
    denied = client.get("/v1/status")
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "UNAUTHORIZED"
    response = client.get(
        "/v1/status", headers={"Authorization": f"Bearer {'k' * 32}"}
    )
    assert response.status_code == 200


def test_authentication_uses_constant_time_comparison(monkeypatch) -> None:
    compared = []

    def compare(left: str, right: str) -> bool:
        compared.append((left, right))
        return False

    monkeypatch.setattr("schwabber.auth.hmac.compare_digest", compare)
    response = TestClient(build_app(settings())).get(
        "/v1/status",
        headers={"Authorization": "Bearer supplied-key"},
    )
    assert response.status_code == 401
    assert compared == [("supplied-key", "k" * 32)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_app.py -q`

Expected: FAIL because `schwabber.app` does not exist.

- [ ] **Step 3: Implement bearer verification and a minimal app**

```python
# src/schwabber/auth.py
import hmac

from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from schwabber.errors import Unauthorized

bearer = HTTPBearer(auto_error=False)


async def require_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> None:
    expected = request.app.state.settings.api_key
    supplied = credentials.credentials if credentials else ""
    if not hmac.compare_digest(supplied, expected):
        raise Unauthorized("Missing or invalid API key")
```

```python
# src/schwabber/app.py
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from schwabber.auth import bearer, require_api_key
from schwabber.config import Settings
from schwabber.errors import AppError


def build_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="Schwabber", version="0.1.0")
    app.state.settings = settings

    async def authorized(
        request: Request,
        credentials=Depends(bearer),
    ) -> None:
        await require_api_key(request, credentials)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid4()))
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "retryable": exc.retryable,
                    "retry_after_seconds": exc.retry_after_seconds,
                    "request_id": request_id,
                }
            },
        )

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/v1/status", dependencies=[Depends(authorized)])
    async def status() -> dict[str, str]:
        return {"status": "degraded"}

    return app
```

- [ ] **Step 4: Run app tests**

Run: `.venv/bin/pytest tests/test_app.py -q`

Expected: `3 passed`.

- [ ] **Step 5: Commit the app skeleton**

```bash
git add src/schwabber/auth.py src/schwabber/app.py tests/test_app.py
git commit -m "feat: add authenticated FastAPI skeleton"
```

### Task 5: Add bounded cache and deadline-aware retries

**Files:**
- Create: `src/schwabber/cache.py`
- Create: `src/schwabber/retry.py`
- Create: `tests/test_cache.py`
- Create: `tests/test_retry.py`

- [ ] **Step 1: Write failing primitive tests**

```python
# tests/test_cache.py
from schwabber.cache import TtlLruCache


def test_cache_expires_and_evicts_oldest_entry() -> None:
    now = [0.0]
    cache = TtlLruCache[str, int](max_entries=2, clock=lambda: now[0])
    cache.set("a", 1, ttl_seconds=5)
    cache.set("b", 2, ttl_seconds=5)
    cache.set("c", 3, ttl_seconds=5)
    assert cache.get("a") is None
    now[0] = 6
    assert cache.get("b") is None
```

```python
# tests/test_retry.py
import pytest

from schwabber.retry import retry_async


@pytest.mark.asyncio
async def test_retry_stops_after_two_retries() -> None:
    calls = 0

    async def failing() -> int:
        nonlocal calls
        calls += 1
        raise RuntimeError("transient")

    with pytest.raises(RuntimeError, match="transient"):
        await retry_async(
            failing,
            should_retry=lambda exc: True,
            attempts=3,
            deadline_seconds=25,
            sleep=lambda _: _no_sleep(),
        )
    assert calls == 3


async def _no_sleep() -> None:
    return None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_cache.py tests/test_retry.py -q`

Expected: FAIL because both modules are absent.

- [ ] **Step 3: Implement the primitives**

```python
# src/schwabber/cache.py
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


@dataclass
class _Entry(Generic[V]):
    value: V
    stored_at: float
    expires_at: float


class TtlLruCache(Generic[K, V]):
    def __init__(
        self,
        max_entries: int = 1024,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[K, _Entry[V]] = OrderedDict()

    def get(self, key: K) -> tuple[V, int] | None:
        entry = self._entries.get(key)
        now = self._clock()
        if entry is None:
            return None
        if now >= entry.expires_at:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return entry.value, int(now - entry.stored_at)

    def set(self, key: K, value: V, ttl_seconds: int) -> None:
        now = self._clock()
        self._entries[key] = _Entry(value, now, now + ttl_seconds)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
```

```python
# src/schwabber/retry.py
import asyncio
import random
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import TypeVar

T = TypeVar("T")


async def retry_async(
    operation: Callable[[], Awaitable[T]],
    *,
    should_retry: Callable[[Exception], bool],
    attempts: int = 3,
    deadline_seconds: float = 25,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
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
            await sleep(delay)
    raise AssertionError("retry loop exhausted without returning or raising")
```

- [ ] **Step 4: Run primitive tests**

Run: `.venv/bin/pytest tests/test_cache.py tests/test_retry.py -q`

Expected: `2 passed`.

- [ ] **Step 5: Commit primitives**

```bash
git add src/schwabber/cache.py src/schwabber/retry.py tests/test_cache.py tests/test_retry.py
git commit -m "feat: add cache and retry primitives"
```

### Task 6: Implement token status and manual authorization CLI

**Files:**
- Create: `src/schwabber/token_status.py`
- Create: `src/schwabber/cli.py`
- Create: `tests/test_token_status.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write failing token and CLI tests**

```python
# tests/test_token_status.py
from datetime import UTC, datetime

from schwabber.token_status import classify_token, classify_token_file


NOW = datetime(2026, 8, 28, tzinfo=UTC)


def test_token_status_uses_creation_timestamp() -> None:
    status = classify_token(
        now=NOW,
        creation_timestamp=int(NOW.timestamp()) - 6 * 86_400,
        warn_days=6,
        max_days=7,
    )
    assert status.state == "URGENT"
    assert status.days_left == 1


def test_token_file_reads_schwab_py_creation_timestamp(tmp_path) -> None:
    path = tmp_path / "token.json"
    path.write_text(
        '{"creation_timestamp": 1787356800, "token": {"access_token": "secret"}}'
    )
    status = classify_token_file(
        path=path,
        now=NOW,
        warn_days=6,
        max_days=7,
    )
    assert status.state == "URGENT"
```

```python
# tests/test_cli.py
import stat

import schwab.auth

from schwabber.cli import auth_login, build_parser
from schwabber.config import Settings


def test_cli_parses_auth_login() -> None:
    args = build_parser().parse_args(["auth", "login"])
    assert args.command == "auth"
    assert args.auth_command == "login"


def test_auth_login_sets_private_token_permissions(monkeypatch, tmp_path) -> None:
    token_path = tmp_path / "token.json"

    def manual_flow(api_key, app_secret, callback_url, path, **kwargs):
        token_path.write_text("{}")
        return object()

    monkeypatch.setattr(schwab.auth, "client_from_manual_flow", manual_flow)
    settings = Settings.from_mapping(
        {
            "SCHWABBER_API_KEY": "k" * 32,
            "SCHWAB_CLIENT_ID": "client-id",
            "SCHWAB_CLIENT_SECRET": "client-secret",
            "SCHWAB_TOKEN_PATH": str(token_path),
        }
    )
    auth_login(settings)
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_token_status.py tests/test_cli.py -q`

Expected: FAIL because token and CLI modules are absent.

- [ ] **Step 3: Implement token classification and CLI parsing**

```python
# src/schwabber/token_status.py
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class TokenStatus:
    state: Literal["OK", "URGENT", "EXPIRED", "MISSING", "UNAVAILABLE"]
    days_left: int | None
    expires_at: datetime | None


def classify_token(
    *,
    now: datetime,
    creation_timestamp: int | None,
    warn_days: int,
    max_days: int,
) -> TokenStatus:
    if creation_timestamp is None:
        return TokenStatus("MISSING", None, None)
    created = datetime.fromtimestamp(creation_timestamp, tz=UTC)
    created = min(created, now)
    age = now - created
    expires_at = created + timedelta(days=max_days)
    days_left = max((expires_at - now).days, 0)
    if age >= timedelta(days=max_days):
        state = "EXPIRED"
    elif age >= timedelta(days=warn_days):
        state = "URGENT"
    else:
        state = "OK"
    return TokenStatus(state, days_left, expires_at)


def classify_token_file(
    *,
    path: Path,
    now: datetime,
    warn_days: int,
    max_days: int,
) -> TokenStatus:
    if not path.exists():
        return TokenStatus("MISSING", None, None)
    try:
        payload = json.loads(path.read_text())
        creation_timestamp = payload["creation_timestamp"]
        if not isinstance(creation_timestamp, int):
            raise TypeError("creation_timestamp is not an integer")
    except (OSError, ValueError, KeyError, TypeError):
        return TokenStatus("UNAVAILABLE", None, None)
    return classify_token(
        now=now,
        creation_timestamp=creation_timestamp,
        warn_days=warn_days,
        max_days=max_days,
    )
```

```python
# src/schwabber/cli.py
import argparse
import os

from schwabber.config import ConfigurationError, Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="schwabber")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve")
    auth = commands.add_parser("auth").add_subparsers(
        dest="auth_command", required=True
    )
    auth.add_parser("login")
    smoke = commands.add_parser("smoke")
    smoke.add_argument("symbol")
    return parser


def auth_login(settings: Settings) -> None:
    if not settings.schwab_configured:
        raise ConfigurationError(
            "SCHWAB_CLIENT_ID and SCHWAB_CLIENT_SECRET are required"
        )
    from schwab.auth import client_from_manual_flow

    settings.token_path.parent.mkdir(parents=True, exist_ok=True)
    client_from_manual_flow(
        settings.schwab_client_id,
        settings.schwab_client_secret,
        settings.callback_url,
        str(settings.token_path),
        enforce_enums=False,
    )
    os.chmod(settings.token_path, 0o600)


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings.from_env()
    if args.command == "auth" and args.auth_command == "login":
        auth_login(settings)
        return
    if args.command == "serve":
        import uvicorn

        uvicorn.run("schwabber.app:create_app", factory=True, host="0.0.0.0", port=8000)
        return
    raise SystemExit("smoke is added after market routes are implemented")
```

- [ ] **Step 4: Run token and CLI tests**

Run: `.venv/bin/pytest tests/test_token_status.py tests/test_cli.py -q`

Expected: `3 passed`.

- [ ] **Step 5: Commit token workflow**

```bash
git add src/schwabber/token_status.py src/schwabber/cli.py tests/test_token_status.py tests/test_cli.py
git commit -m "feat: add Schwab authorization workflow"
```

### Task 7: Define market schemas and provider protocol

**Files:**
- Create: `src/schwabber/schemas/market.py`
- Create: `src/schwabber/providers/__init__.py`
- Create: `src/schwabber/providers/base.py`
- Create: `tests/test_market_schemas.py`

- [ ] **Step 1: Write the failing quote-schema test**

```python
# tests/test_market_schemas.py
from schwabber.schemas.market import Quote


def test_quote_keeps_unknown_market_fields_nullable() -> None:
    quote = Quote(symbol="AMD", last_price=172.34)
    assert quote.bid_price is None
    assert quote.is_realtime is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_market_schemas.py -q`

Expected: FAIL because `schwabber.schemas.market` is absent.

- [ ] **Step 3: Add normalized models and the provider contract**

```python
# src/schwabber/schemas/market.py
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class Quote(BaseModel):
    symbol: str
    asset_type: str | None = None
    last_price: float | None = None
    bid_price: float | None = None
    ask_price: float | None = None
    mark: float | None = None
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    close_price: float | None = None
    total_volume: int | None = None
    quote_time: datetime | None = None
    trade_time: datetime | None = None
    is_realtime: bool | None = None


class Candle(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class Instrument(BaseModel):
    symbol: str
    description: str | None = None
    exchange: str | None = None
    asset_type: str | None = None
    market_cap: float | None = None
    pe_ratio: float | None = None
    eps: float | None = None
    dividend_yield: float | None = None
    beta: float | None = None
    shares_outstanding: float | None = None
    week_52_high: float | None = None
    week_52_low: float | None = None


class OptionContract(BaseModel):
    symbol: str
    underlying: str
    expiration: date
    strike: float
    put_call: Literal["PUT", "CALL"]
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    mark: float | None = None
    volume: int | None = None
    open_interest: int | None = None
    implied_volatility: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    rho: float | None = None
    quote_time: datetime | None = None
    is_realtime: bool | None = None


class Mover(BaseModel):
    symbol: str
    description: str | None = None
    last_price: float | None = None
    change: float | None = None
    percent_change: float | None = None
    volume: int | None = None


class MarketHours(BaseModel):
    market: str
    product: str | None = None
    date: date
    is_open: bool
    pre_market_start: datetime | None = None
    pre_market_end: datetime | None = None
    regular_start: datetime | None = None
    regular_end: datetime | None = None
    post_market_start: datetime | None = None
    post_market_end: datetime | None = None


class CollectionResult(BaseModel):
    truncated: bool = False
```

```python
# src/schwabber/providers/base.py
from datetime import date
from typing import Protocol

from schwabber.schemas.market import (
    Candle,
    Instrument,
    MarketHours,
    Mover,
    OptionContract,
    Quote,
)


class MarketProvider(Protocol):
    async def quotes(self, symbols: tuple[str, ...]) -> list[Quote]: ...
    async def instrument(self, symbol: str) -> Instrument: ...
    async def history(
        self, symbol: str, start: date, end: date, frequency: str, extended: bool
    ) -> list[Candle]: ...
    async def options(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
        put_call: str,
        strike_count: int,
    ) -> list[OptionContract]: ...
    async def movers(
        self, index: str, direction: str, frequency: int
    ) -> list[Mover]: ...
    async def market_hours(
        self, markets: tuple[str, ...], day: date
    ) -> list[MarketHours]: ...
```

```python
# src/schwabber/providers/__init__.py
"""External data providers."""
```

- [ ] **Step 4: Run schema tests**

Run: `.venv/bin/pytest tests/test_market_schemas.py -q`

Expected: `1 passed`.

- [ ] **Step 5: Commit market contracts**

```bash
git add src/schwabber/schemas/market.py src/schwabber/providers tests/test_market_schemas.py
git commit -m "feat: define market data contracts"
```

### Task 8: Implement Schwab quotes and instruments

**Files:**
- Create: `src/schwabber/providers/schwab.py`
- Create: `tests/fixtures/schwab_quotes.json`
- Create: `tests/fixtures/schwab_instruments.json`
- Create: `tests/test_schwab_provider.py`

- [ ] **Step 1: Add synthetic fixtures and failing normalization tests**

```python
# tests/test_schwab_provider.py
import json
from pathlib import Path

import pytest

from schwabber.providers.schwab import SchwabMarketProvider


class Response:
    def __init__(self, body: dict):
        self.status_code = 200
        self._body = body

    def json(self) -> dict:
        return self._body


@pytest.mark.asyncio
async def test_quotes_normalize_synthetic_schwab_payload() -> None:
    body = json.loads(Path("tests/fixtures/schwab_quotes.json").read_text())

    class Client:
        async def get_quotes(self, symbols):
            return Response(body)

    result = await SchwabMarketProvider(Client()).quotes(("AMD",))
    assert result[0].symbol == "AMD"
    assert result[0].bid_price == 172.30


@pytest.mark.asyncio
async def test_instrument_normalizes_fundamentals() -> None:
    body = json.loads(Path("tests/fixtures/schwab_instruments.json").read_text())

    class Client:
        async def get_instruments(self, symbols, projection):
            return Response(body)

    result = await SchwabMarketProvider(Client()).instrument("AMD")
    assert result.market_cap == 278_000_000_000
```

**`tests/fixtures/schwab_quotes.json`:**

```json
{
  "AMD": {
    "assetMainType": "EQUITY",
    "quote": {
      "bidPrice": 172.3,
      "askPrice": 172.4,
      "lastPrice": 172.34,
      "mark": 172.35,
      "totalVolume": 42100000,
      "quoteTime": 1787927400000,
      "tradeTime": 1787927398000
    },
    "reference": {"isRealtime": true},
    "regular": {
      "regularMarketOpen": 170.0,
      "regularMarketHigh": 174.0,
      "regularMarketLow": 169.5,
      "regularMarketLastPrice": 172.34
    }
  }
}
```

**`tests/fixtures/schwab_instruments.json`:**

```json
{
  "instruments": [
    {
      "symbol": "AMD",
      "description": "Synthetic Semiconductor Company",
      "exchange": "NASDAQ",
      "assetType": "EQUITY",
      "fundamental": {
        "marketCap": 278000000000,
        "peRatio": 31.2,
        "epsTTM": 5.52,
        "divYield": 0.0,
        "beta": 1.7,
        "sharesOutstanding": 1610000000,
        "high52": 188.0,
        "low52": 92.0
      }
    }
  ]
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_schwab_provider.py -q`

Expected: FAIL because `SchwabMarketProvider` is absent.

- [ ] **Step 3: Implement the client wrapper and normalizers**

```python
# src/schwabber/providers/schwab.py
from datetime import UTC, datetime
from typing import Any

from schwabber.errors import ResourceNotFound, UpstreamFailure
from schwabber.schemas.market import Instrument, Quote


def _epoch_ms(value: int | None) -> datetime | None:
    return datetime.fromtimestamp(value / 1000, tz=UTC) if value is not None else None


def _field(*sources: dict[str, Any], names: tuple[str, ...]) -> Any:
    for source in sources:
        for name in names:
            if name in source:
                return source[name]
    return None


class SchwabMarketProvider:
    def __init__(self, client: Any):
        self._client = client

    async def _json(self, awaitable) -> dict[str, Any]:
        response = await awaitable
        if response.status_code == 404:
            raise ResourceNotFound("Schwab resource not found")
        if response.status_code >= 400:
            raise UpstreamFailure(f"Schwab returned HTTP {response.status_code}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise UpstreamFailure("Schwab returned a non-object response")
        return payload

    async def quotes(self, symbols: tuple[str, ...]) -> list[Quote]:
        payload = await self._json(self._client.get_quotes(list(symbols)))
        results: list[Quote] = []
        for symbol in symbols:
            item = payload.get(symbol, {})
            quote = item.get("quote", {})
            regular = item.get("regular", {})
            reference = item.get("reference", {})
            results.append(
                Quote(
                    symbol=symbol,
                    asset_type=item.get("assetMainType"),
                    last_price=_field(quote, regular, names=("lastPrice", "regularMarketLastPrice")),
                    bid_price=quote.get("bidPrice"),
                    ask_price=quote.get("askPrice"),
                    mark=_field(quote, names=("mark", "markPrice")),
                    open_price=_field(regular, quote, names=("regularMarketOpen", "openPrice")),
                    high_price=_field(regular, quote, names=("regularMarketHigh", "highPrice")),
                    low_price=_field(regular, quote, names=("regularMarketLow", "lowPrice")),
                    close_price=_field(regular, quote, names=("regularMarketLastPrice", "closePrice")),
                    total_volume=quote.get("totalVolume"),
                    quote_time=_epoch_ms(quote.get("quoteTime")),
                    trade_time=_epoch_ms(quote.get("tradeTime")),
                    is_realtime=reference.get("isRealtime"),
                )
            )
        return results

    async def instrument(self, symbol: str) -> Instrument:
        payload = await self._json(
            self._client.get_instruments(symbol, projection="FUNDAMENTAL")
        )
        item = next(iter(payload.get("instruments", [])), None)
        if item is None:
            raise ResourceNotFound(f"No instrument found for {symbol}")
        fundamental = item.get("fundamental", {})
        return Instrument(
            symbol=item.get("symbol", symbol),
            description=item.get("description"),
            exchange=item.get("exchange"),
            asset_type=item.get("assetType"),
            market_cap=fundamental.get("marketCap"),
            pe_ratio=fundamental.get("peRatio"),
            eps=fundamental.get("epsTTM"),
            dividend_yield=fundamental.get("divYield"),
            beta=fundamental.get("beta"),
            shares_outstanding=fundamental.get("sharesOutstanding"),
            week_52_high=fundamental.get("high52"),
            week_52_low=fundamental.get("low52"),
        )
```

- [ ] **Step 4: Run provider tests**

Run: `.venv/bin/pytest tests/test_schwab_provider.py -q`

Expected: `2 passed`.

- [ ] **Step 5: Commit quotes and instruments**

```bash
git add src/schwabber/providers/schwab.py tests/fixtures tests/test_schwab_provider.py
git commit -m "feat: add Schwab quotes and instruments"
```

### Task 9: Add price history and option-chain normalization

**Files:**
- Modify: `src/schwabber/providers/schwab.py`
- Create: `tests/fixtures/schwab_history.json`
- Create: `tests/fixtures/schwab_options.json`
- Modify: `tests/test_schwab_provider.py`

- [ ] **Step 1: Write failing history and option tests**

```python
# Add to tests/test_schwab_provider.py imports
from datetime import date


@pytest.mark.asyncio
async def test_history_converts_epoch_milliseconds() -> None:
    body = json.loads(Path("tests/fixtures/schwab_history.json").read_text())

    class Client:
        async def get_price_history(self, **kwargs):
            return Response(body)

    result = await SchwabMarketProvider(Client()).history(
        "AMD", date(2026, 8, 1), date(2026, 8, 2), "1d", False
    )
    assert result[0].open == 170.0
    assert result[0].timestamp.tzinfo is not None


@pytest.mark.asyncio
async def test_options_flatten_calls_and_puts() -> None:
    body = json.loads(Path("tests/fixtures/schwab_options.json").read_text())

    class Client:
        async def get_option_chain(self, symbol, **kwargs):
            return Response(body)

    result = await SchwabMarketProvider(Client()).options(
        "AMD", date(2026, 9, 1), date(2026, 10, 15), "ALL", 10
    )
    assert {contract.put_call for contract in result} == {"CALL", "PUT"}
    assert result[0].implied_volatility is not None
```

**`tests/fixtures/schwab_history.json`:**

```json
{
  "symbol": "AMD",
  "empty": false,
  "candles": [
    {
      "datetime": 1785542400000,
      "open": 170.0,
      "high": 174.0,
      "low": 169.0,
      "close": 173.0,
      "volume": 42000000
    },
    {
      "datetime": 1785628800000,
      "open": 173.0,
      "high": 176.0,
      "low": 171.5,
      "close": 175.0,
      "volume": 39000000
    }
  ]
}
```

**`tests/fixtures/schwab_options.json`:**

```json
{
  "symbol": "AMD",
  "callExpDateMap": {
    "2026-09-18:21": {
      "170.0": [
        {
          "symbol": "AMD  260918C00170000",
          "bid": 8.1,
          "ask": 8.3,
          "last": 8.2,
          "mark": 8.2,
          "totalVolume": 120,
          "openInterest": 2200,
          "volatility": 42.5,
          "delta": 0.57,
          "gamma": 0.03,
          "theta": -0.08,
          "vega": 0.12,
          "rho": 0.02,
          "quoteTimeInLong": 1787927400000,
          "realtime": true
        }
      ]
    }
  },
  "putExpDateMap": {
    "2026-09-18:21": {
      "170.0": [
        {
          "symbol": "AMD  260918P00170000",
          "bid": 5.0,
          "ask": 5.2,
          "last": 5.1,
          "mark": 5.1,
          "totalVolume": 80,
          "openInterest": 1800,
          "volatility": 43.1,
          "delta": -0.43,
          "gamma": 0.03,
          "theta": -0.07,
          "vega": 0.11,
          "rho": -0.02,
          "quoteTimeInLong": 1787927400000,
          "realtime": true
        }
      ]
    }
  }
}
```

- [ ] **Step 2: Run targeted tests to verify they fail**

Run: `.venv/bin/pytest tests/test_schwab_provider.py -k "history or options" -q`

Expected: FAIL because the provider lacks both methods.

- [ ] **Step 3: Implement history and options**

```python
# Add to src/schwabber/providers/schwab.py
from datetime import date
from typing import Literal

from schwabber.schemas.market import Candle, OptionContract


def _required_epoch_ms(value: int) -> datetime:
    parsed = _epoch_ms(value)
    if parsed is None:
        raise UpstreamFailure("Schwab candle is missing a timestamp")
    return parsed


    async def history(
        self,
        symbol: str,
        start: date,
        end: date,
        frequency: str,
        extended: bool,
    ) -> list[Candle]:
        frequency_map = {
            "1m": ("minute", 1),
            "5m": ("minute", 5),
            "15m": ("minute", 15),
            "30m": ("minute", 30),
            "1d": ("daily", 1),
            "1w": ("weekly", 1),
        }
        frequency_type, frequency_value = frequency_map[frequency]
        payload = await self._json(
            self._client.get_price_history(
                symbol=symbol,
                start_datetime=datetime.combine(start, datetime.min.time(), tzinfo=UTC),
                end_datetime=datetime.combine(end, datetime.max.time(), tzinfo=UTC),
                frequency_type=frequency_type,
                frequency=frequency_value,
                need_extended_hours_data=extended,
            )
        )
        return [
            Candle(
                timestamp=_required_epoch_ms(candle["datetime"]),
                open=candle["open"],
                high=candle["high"],
                low=candle["low"],
                close=candle["close"],
                volume=candle["volume"],
            )
            for candle in payload.get("candles", [])
        ]

    async def options(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
        put_call: str,
        strike_count: int,
    ) -> list[OptionContract]:
        payload = await self._json(
            self._client.get_option_chain(
                symbol,
                contract_type=put_call,
                strike_count=strike_count,
                from_date=from_date,
                to_date=to_date,
            )
        )
        results: list[OptionContract] = []
        for map_name in ("callExpDateMap", "putExpDateMap"):
            side: Literal["CALL", "PUT"] = (
                "CALL" if map_name == "callExpDateMap" else "PUT"
            )
            for expiry_key, strikes in payload.get(map_name, {}).items():
                expiry = date.fromisoformat(expiry_key.split(":", 1)[0])
                for strike_key, contracts in strikes.items():
                    for item in contracts:
                        results.append(
                            OptionContract(
                                symbol=item["symbol"],
                                underlying=payload.get("symbol", symbol),
                                expiration=expiry,
                                strike=float(strike_key),
                                put_call=side,
                                bid=item.get("bid"),
                                ask=item.get("ask"),
                                last=item.get("last"),
                                mark=item.get("mark"),
                                volume=item.get("totalVolume"),
                                open_interest=item.get("openInterest"),
                                implied_volatility=item.get("volatility"),
                                delta=item.get("delta"),
                                gamma=item.get("gamma"),
                                theta=item.get("theta"),
                                vega=item.get("vega"),
                                rho=item.get("rho"),
                                quote_time=_epoch_ms(item.get("quoteTimeInLong")),
                                is_realtime=item.get("realtime"),
                            )
                        )
        return results
```

- [ ] **Step 4: Run provider tests**

Run: `.venv/bin/pytest tests/test_schwab_provider.py -q`

Expected: `4 passed`.

- [ ] **Step 5: Commit history and options**

```bash
git add src/schwabber/providers/schwab.py tests/fixtures tests/test_schwab_provider.py
git commit -m "feat: add Schwab history and options"
```

### Task 10: Add movers and market-hours normalization

**Files:**
- Modify: `src/schwabber/providers/schwab.py`
- Create: `tests/fixtures/schwab_market_hours.json`
- Modify: `tests/test_schwab_provider.py`

- [ ] **Step 1: Write failing mover and hours tests**

```python
@pytest.mark.asyncio
async def test_movers_are_normalized() -> None:
    class Client:
        async def get_movers(self, index, **kwargs):
            return Response({"screeners": [{"symbol": "AMD", "lastPrice": 180.0}]})

    result = await SchwabMarketProvider(Client()).movers("$SPX", "UP", 10)
    assert result[0].symbol == "AMD"


@pytest.mark.asyncio
async def test_market_hours_extract_regular_session() -> None:
    body = json.loads(Path("tests/fixtures/schwab_market_hours.json").read_text())

    class Client:
        async def get_market_hours(self, markets, date):
            return Response(body)

    result = await SchwabMarketProvider(Client()).market_hours(
        ("equity",), date(2026, 8, 28)
    )
    assert result[0].market == "equity"
    assert result[0].regular_start is not None
    assert result[0].pre_market_start is not None
    assert result[0].post_market_end is not None
```

**`tests/fixtures/schwab_market_hours.json`:**

```json
{
  "equity": {
    "EQ": {
      "isOpen": true,
      "sessionHours": {
        "preMarket": [
          {
            "start": "2026-08-28T07:00:00-04:00",
            "end": "2026-08-28T09:30:00-04:00"
          }
        ],
        "regularMarket": [
          {
            "start": "2026-08-28T09:30:00-04:00",
            "end": "2026-08-28T16:00:00-04:00"
          }
        ],
        "postMarket": [
          {
            "start": "2026-08-28T16:00:00-04:00",
            "end": "2026-08-28T20:00:00-04:00"
          }
        ]
      }
    }
  }
}
```

- [ ] **Step 2: Run targeted tests to verify they fail**

Run: `.venv/bin/pytest tests/test_schwab_provider.py -k "movers or market_hours" -q`

Expected: FAIL because the provider lacks both methods.

- [ ] **Step 3: Implement mover and hours parsing**

```python
# Add to src/schwabber/providers/schwab.py
from schwabber.schemas.market import MarketHours, Mover


def _first_session(
    sessions: dict[str, Any], name: str
) -> dict[str, Any]:
    values = sessions.get(name)
    return values[0] if isinstance(values, list) and values else {}


    async def movers(
        self, index: str, direction: str, frequency: int
    ) -> list[Mover]:
        payload = await self._json(
            self._client.get_movers(
                index,
                sort_order=direction,
                frequency=frequency,
            )
        )
        return [
            Mover(
                symbol=item["symbol"],
                description=item.get("description"),
                last_price=item.get("lastPrice"),
                change=item.get("netChange"),
                percent_change=item.get("percentChange"),
                volume=item.get("totalVolume"),
            )
            for item in payload.get("screeners", [])
        ]

    async def market_hours(
        self, markets: tuple[str, ...], day: date
    ) -> list[MarketHours]:
        payload = await self._json(
            self._client.get_market_hours(list(markets), date=day)
        )
        results: list[MarketHours] = []
        for market, products in payload.items():
            for product, item in products.items():
                sessions = item.get("sessionHours", {})
                pre_market = _first_session(sessions, "preMarket")
                regular = _first_session(sessions, "regularMarket")
                post_market = _first_session(sessions, "postMarket")
                results.append(
                    MarketHours(
                        market=market,
                        product=product,
                        date=day,
                        is_open=item.get("isOpen", False),
                        pre_market_start=pre_market.get("start"),
                        pre_market_end=pre_market.get("end"),
                        regular_start=regular.get("start"),
                        regular_end=regular.get("end"),
                        post_market_start=post_market.get("start"),
                        post_market_end=post_market.get("end"),
                    )
                )
        return results
```

- [ ] **Step 4: Run provider tests**

Run: `.venv/bin/pytest tests/test_schwab_provider.py -q`

Expected: `6 passed`.

- [ ] **Step 5: Commit movers and hours**

```bash
git add src/schwabber/providers/schwab.py tests/fixtures tests/test_schwab_provider.py
git commit -m "feat: add Schwab movers and market hours"
```

### Task 11: Add the cached market service and validation rules

**Files:**
- Create: `src/schwabber/services/__init__.py`
- Create: `src/schwabber/services/market.py`
- Create: `tests/test_market_service.py`

- [ ] **Step 1: Write failing cache and bounds tests**

```python
# tests/test_market_service.py
from datetime import UTC, date, datetime, timedelta

import pytest

from schwabber.cache import TtlLruCache
from schwabber.errors import InvalidRequest
from schwabber.schemas.market import Candle, Mover, OptionContract, Quote
from schwabber.services.market import MarketService


class Provider:
    quote_calls = 0

    async def quotes(self, symbols):
        self.quote_calls += 1
        return [Quote(symbol=symbol, last_price=1.0) for symbol in symbols]

    async def history(self, symbol, start, end, frequency, extended):
        first = datetime(2026, 1, 1, tzinfo=UTC)
        return [
            Candle(
                timestamp=first + timedelta(days=index),
                open=1.0,
                high=2.0,
                low=0.5,
                close=1.5,
                volume=100,
            )
            for index in range(501)
        ]

    async def options(self, symbol, from_date, to_date, put_call, strike_count):
        return [
            OptionContract(
                symbol=f"AMD-{index}",
                underlying="AMD",
                expiration=date(2026, 9, 18),
                strike=float(index),
                put_call="CALL",
                open_interest=index,
            )
            for index in range(250)
        ]

    async def movers(self, index, direction, frequency):
        return [Mover(symbol=f"S{item}") for item in range(60)]


@pytest.mark.asyncio
async def test_quotes_report_cache_hit_on_second_call() -> None:
    provider = Provider()
    service = MarketService(provider, TtlLruCache())
    first = await service.quotes(("AMD",))
    second = await service.quotes(("AMD",))
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert provider.quote_calls == 1


def test_one_minute_history_rejects_more_than_ten_days() -> None:
    with pytest.raises(InvalidRequest, match="10 calendar days"):
        MarketService.validate_history_window(
            date(2026, 8, 1), date(2026, 8, 12), "1m"
        )


@pytest.mark.asyncio
async def test_history_keeps_latest_500_and_marks_truncation() -> None:
    service = MarketService(Provider(), TtlLruCache())
    result = await service.history(
        "AMD", date(2026, 1, 1), date(2030, 1, 1), "1d", False
    )
    assert len(result.data) == 500
    assert result.data[0].timestamp == datetime(2026, 1, 2, tzinfo=UTC)
    assert result.truncated is True


@pytest.mark.asyncio
async def test_options_filter_open_interest_before_cap() -> None:
    service = MarketService(Provider(), TtlLruCache())
    result = await service.options(
        "AMD",
        date(2026, 9, 1),
        date(2026, 10, 1),
        "ALL",
        50,
        minimum_open_interest=25,
    )
    assert len(result.data) == 200
    assert result.data[0].open_interest == 25
    assert result.truncated is True


@pytest.mark.asyncio
async def test_movers_respect_requested_limit() -> None:
    service = MarketService(Provider(), TtlLruCache())
    result = await service.movers("$SPX", "UP", 10, limit=50)
    assert len(result.data) == 50
    assert result.truncated is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_market_service.py -q`

Expected: FAIL because `MarketService` is absent.

- [ ] **Step 3: Implement result metadata, cache, and validation**

```python
# src/schwabber/services/market.py
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Generic, TypeVar, cast

from schwabber.cache import TtlLruCache
from schwabber.errors import InvalidRequest
from schwabber.providers.base import MarketProvider
from schwabber.schemas.market import (
    Candle,
    Instrument,
    MarketHours,
    Mover,
    OptionContract,
    Quote,
)

T = TypeVar("T")


@dataclass(frozen=True)
class ServiceResult(Generic[T]):
    data: T
    retrieved_at: datetime
    cache_hit: bool
    cache_age_seconds: int
    truncated: bool = False


class MarketService:
    def __init__(
        self,
        provider: MarketProvider,
        cache: TtlLruCache[tuple[object, ...], object],
    ) -> None:
        self._provider = provider
        self._cache = cache

    async def _load(
        self,
        key: tuple[object, ...],
        ttl: int,
        loader: Callable[[], Awaitable[T]],
    ) -> ServiceResult[T]:
        cached = self._cache.get(key)
        if cached is not None:
            value, age = cached
            result = cast(ServiceResult[T], value)
            return ServiceResult(
                data=result.data,
                retrieved_at=result.retrieved_at,
                cache_hit=True,
                cache_age_seconds=age,
                truncated=result.truncated,
            )
        fresh = ServiceResult(
            data=await loader(),
            retrieved_at=datetime.now(UTC),
            cache_hit=False,
            cache_age_seconds=0,
        )
        self._cache.set(key, fresh, ttl)
        return fresh

    async def _load_bounded_list(
        self,
        key: tuple[object, ...],
        ttl: int,
        loader: Callable[[], Awaitable[list[T]]],
        *,
        cap: int,
        keep_latest: bool = False,
    ) -> ServiceResult[list[T]]:
        cached = self._cache.get(key)
        if cached is not None:
            value, age = cached
            stored = cast(ServiceResult[list[T]], value)
            return ServiceResult(
                stored.data,
                stored.retrieved_at,
                True,
                age,
                stored.truncated,
            )
        values = await loader()
        truncated = len(values) > cap
        bounded = values[-cap:] if keep_latest else values[:cap]
        result = ServiceResult(
            bounded,
            datetime.now(UTC),
            False,
            0,
            truncated,
        )
        self._cache.set(key, result, ttl)
        return result

    async def quotes(self, symbols: tuple[str, ...]) -> ServiceResult[list[Quote]]:
        if not 1 <= len(symbols) <= 25:
            raise InvalidRequest("quotes require between 1 and 25 symbols")
        return await self._load(
            ("quotes", *symbols),
            5,
            lambda: self._provider.quotes(symbols),
        )

    async def instrument(self, symbol: str) -> ServiceResult[Instrument]:
        return await self._load(
            ("instrument", symbol),
            300,
            lambda: self._provider.instrument(symbol),
        )

    @staticmethod
    def validate_history_window(start: date, end: date, frequency: str) -> None:
        max_days = {
            "1m": 10,
            "5m": 60,
            "15m": 60,
            "30m": 60,
            "1d": 5 * 366,
            "1w": 20 * 366,
        }
        if start > end:
            raise InvalidRequest("start must not be after end")
        if frequency not in max_days:
            raise InvalidRequest(f"Unsupported history frequency: {frequency}")
        if (end - start).days > max_days[frequency]:
            raise InvalidRequest(
                f"{frequency} history supports at most "
                f"{max_days[frequency]} calendar days"
            )

    async def history(
        self,
        symbol: str,
        start: date,
        end: date,
        frequency: str,
        extended: bool,
    ) -> ServiceResult[list[Candle]]:
        self.validate_history_window(start, end, frequency)
        ttl = 15 if frequency in {"1m", "5m", "15m", "30m"} else 300
        key = ("history", symbol, start, end, frequency, extended)
        return await self._load_bounded_list(
            key,
            ttl,
            lambda: self._provider.history(
                symbol, start, end, frequency, extended
            ),
            cap=500,
            keep_latest=True,
        )

    async def options(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
        put_call: str,
        strike_count: int,
        minimum_open_interest: int,
    ) -> ServiceResult[list[OptionContract]]:
        if from_date > to_date:
            raise InvalidRequest("from_date must not be after to_date")
        if put_call not in {"ALL", "CALL", "PUT"}:
            raise InvalidRequest("put_call must be ALL, CALL, or PUT")
        if not 1 <= strike_count <= 50:
            raise InvalidRequest("strike_count must be between 1 and 50")
        if minimum_open_interest < 0:
            raise InvalidRequest("minimum_open_interest must not be negative")
        key = (
            "options",
            symbol,
            from_date,
            to_date,
            put_call,
            strike_count,
            minimum_open_interest,
        )

        async def load_options() -> list[OptionContract]:
            values = await self._provider.options(
                symbol, from_date, to_date, put_call, strike_count
            )
            return [
                item
                for item in values
                if (item.open_interest or 0) >= minimum_open_interest
            ]

        return await self._load_bounded_list(
            key,
            15,
            load_options,
            cap=200,
        )

    async def movers(
        self,
        index: str,
        direction: str,
        frequency: int,
        limit: int,
    ) -> ServiceResult[list[Mover]]:
        if not 1 <= limit <= 50:
            raise InvalidRequest("limit must be between 1 and 50")
        key = ("movers", index, direction, frequency, limit)
        return await self._load_bounded_list(
            key,
            30,
            lambda: self._provider.movers(index, direction, frequency),
            cap=limit,
        )

    async def market_hours(
        self,
        markets: tuple[str, ...],
        day: date,
    ) -> ServiceResult[list[MarketHours]]:
        return await self._load(
            ("market_hours", *markets, day),
            60,
            lambda: self._provider.market_hours(markets, day),
        )
```

- [ ] **Step 4: Run service tests**

Run: `.venv/bin/pytest tests/test_market_service.py -q`

Expected: `5 passed`.

- [ ] **Step 5: Commit the service**

```bash
git add src/schwabber/services tests/test_market_service.py
git commit -m "feat: add bounded market service"
```

### Task 12: Expose protected market and status routes

**Files:**
- Create: `src/schwabber/api/__init__.py`
- Create: `src/schwabber/api/dependencies.py`
- Create: `src/schwabber/api/market.py`
- Create: `src/schwabber/api/status.py`
- Create: `src/schwabber/schemas/status.py`
- Modify: `src/schwabber/app.py`
- Create: `tests/test_market_api.py`
- Create: `tests/test_openapi.py`
- Create: `tests/test_response_budget.py`

- [ ] **Step 1: Write failing endpoint contract tests**

```python
# tests/test_market_api.py
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from schwabber.app import build_app
from schwabber.config import Settings
from schwabber.schemas.market import Quote
from schwabber.services.market import ServiceResult


class Service:
    async def quotes(self, symbols):
        return ServiceResult(
            data=[Quote(symbol=s, last_price=100.0) for s in symbols],
            retrieved_at=datetime(2026, 8, 28, tzinfo=UTC),
            cache_hit=False,
            cache_age_seconds=0,
        )


def test_quotes_route_returns_common_envelope() -> None:
    app = build_app(
        Settings.from_mapping({"SCHWABBER_API_KEY": "k" * 32}),
        market_service=Service(),
    )
    response = TestClient(app).get(
        "/v1/quotes?symbols=AMD,AAPL",
        headers={"Authorization": f"Bearer {'k' * 32}"},
    )
    assert response.status_code == 200
    assert response.json()["meta"]["source"] == "schwab"
    assert len(response.json()["data"]) == 2


def test_quote_symbol_count_is_bounded() -> None:
    app = build_app(
        Settings.from_mapping({"SCHWABBER_API_KEY": "k" * 32}),
        market_service=Service(),
    )
    symbols = ",".join(f"S{index}" for index in range(26))
    response = TestClient(app).get(
        f"/v1/quotes?symbols={symbols}",
        headers={"Authorization": f"Bearer {'k' * 32}"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
```

```python
# tests/test_openapi.py
from schwabber.app import build_app
from schwabber.config import Settings


def test_openapi_has_stable_operation_ids_and_bearer_security() -> None:
    schema = build_app(
        Settings.from_mapping({"SCHWABBER_API_KEY": "k" * 32})
    ).openapi()
    assert schema["paths"]["/v1/quotes"]["get"]["operationId"] == "get_quotes"
    assert "HTTPBearer" in schema["components"]["securitySchemes"]
    operation_ids = [
        operation["operationId"]
        for path in schema["paths"].values()
        for method, operation in path.items()
        if method in {"get", "post", "put", "patch", "delete"}
    ]
    assert len(operation_ids) == len(set(operation_ids))
    assert not any(
        word in operation_id
        for operation_id in operation_ids
        for word in ("account", "position", "order", "trade")
    )
```

```python
# tests/test_response_budget.py
from datetime import UTC, datetime

from schwabber.schemas.common import CacheMeta, ResponseMeta, SuccessEnvelope
from schwabber.schemas.market import Candle, OptionContract


def meta(count: int) -> ResponseMeta:
    return ResponseMeta(
        source="schwab",
        retrieved_at=datetime(2026, 8, 28, 23, 59, 59, 999999, tzinfo=UTC),
        request_id="123e4567-e89b-12d3-a456-426614174000",
        cache=CacheMeta(hit=False, age_seconds=0),
        result_count=count,
        truncated=True,
    )


def test_maximum_history_shape_is_under_action_budget() -> None:
    candles = [
        Candle(
            timestamp=datetime(2026, 8, 28, 23, 59, 59, 999999, tzinfo=UTC),
            open=1_234_567.123456,
            high=1_234_567.123456,
            low=1_234_567.123456,
            close=1_234_567.123456,
            volume=999_999_999_999,
        )
        for _ in range(500)
    ]
    body = SuccessEnvelope(data=candles, meta=meta(500)).model_dump_json(
        exclude_none=True
    )
    assert len(body) < 90_000


def test_maximum_option_shape_is_under_action_budget() -> None:
    contracts = [
        OptionContract(
            symbol=f"SYNTHETIC-{index}",
            underlying="SYNTHETIC",
            expiration="2026-12-18",
            strike=1_234_567.12,
            put_call="CALL",
            bid=123.45,
            ask=123.55,
            last=123.50,
            mark=123.50,
            volume=999_999,
            open_interest=999_999,
            implied_volatility=99.999,
            delta=0.999,
            gamma=0.999,
            theta=-0.999,
            vega=0.999,
            rho=0.999,
            quote_time=datetime(2026, 8, 28, tzinfo=UTC),
            is_realtime=True,
        )
        for index in range(200)
    ]
    body = SuccessEnvelope(data=contracts, meta=meta(200)).model_dump_json(
        exclude_none=True
    )
    assert len(body) < 90_000
```

- [ ] **Step 2: Run endpoint tests to verify they fail**

Run: `.venv/bin/pytest tests/test_market_api.py tests/test_openapi.py tests/test_response_budget.py -q`

Expected: FAIL because `build_app` does not accept a service and routes are absent.

- [ ] **Step 3: Implement dependencies, routes, and metadata conversion**

```python
# src/schwabber/api/dependencies.py
from fastapi import Request

from schwabber.errors import ProviderUnavailable
from schwabber.services.market import MarketService


def market_service(request: Request) -> MarketService:
    service = request.app.state.market_service
    if service is None:
        raise ProviderUnavailable("Schwab is not configured or authorized")
    return service
```

```python
# src/schwabber/api/market.py
from datetime import date, timedelta
from typing import Literal, TypeVar

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
T = TypeVar("T")


def envelope(
    request: Request,
    result: ServiceResult[T],
    *,
    filters: dict[str, str | int | bool] | None = None,
) -> SuccessEnvelope[T]:
    return SuccessEnvelope(
        data=result.data,
        meta=ResponseMeta(
            source="schwab",
            retrieved_at=result.retrieved_at,
            request_id=request.state.request_id,
            cache=CacheMeta(
                hit=result.cache_hit,
                age_seconds=result.cache_age_seconds,
            ),
            result_count=len(result.data) if isinstance(result.data, list) else 1,
            truncated=result.truncated,
            filters=filters,
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
):
    normalized = tuple(
        dict.fromkeys(
            symbol.strip().upper()
            for symbol in symbols.split(",")
            if symbol.strip()
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
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    frequency: Literal["1m", "5m", "15m", "30m", "1d", "1w"] = "1d",
    extended_hours: bool = False,
    service: MarketService = Depends(market_service),
) -> SuccessEnvelope[list[Candle]]:
    effective_end = end or date.today()
    effective_start = start or effective_end - timedelta(days=365)
    result = await service.history(
        symbol.upper(),
        effective_start,
        effective_end,
        frequency,
        extended_hours,
    )
    return envelope(
        request,
        result,
        filters={"frequency": frequency, "extended_hours": extended_hours},
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
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    put_call: Literal["ALL", "CALL", "PUT"] = "ALL",
    strike_count: int = Query(default=10, ge=1, le=50),
    minimum_open_interest: int = Query(default=0, ge=0),
    service: MarketService = Depends(market_service),
) -> SuccessEnvelope[list[OptionContract]]:
    effective_from = from_date or date.today()
    effective_to = to_date or effective_from + timedelta(days=45)
    result = await service.options(
        symbol.upper(),
        effective_from,
        effective_to,
        put_call,
        strike_count,
        minimum_open_interest,
    )
    return envelope(
        request,
        result,
        filters={
            "from_date": effective_from.isoformat(),
            "to_date": effective_to.isoformat(),
            "put_call": put_call,
            "strike_count": strike_count,
            "minimum_open_interest": minimum_open_interest,
        },
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
    limit: int = Query(default=10, ge=1, le=50),
    service: MarketService = Depends(market_service),
) -> SuccessEnvelope[list[Mover]]:
    result = await service.movers(index, direction, frequency, limit)
    return envelope(
        request,
        result,
        filters={
            "direction": direction,
            "frequency": frequency,
            "limit": limit,
        },
    )


@router.get(
    "/market-hours",
    operation_id="get_market_hours",
    response_model=SuccessEnvelope[list[MarketHours]],
    response_model_exclude_none=True,
)
async def get_market_hours(
    request: Request,
    day: date = Query(default_factory=date.today),
    markets: Literal["equity", "option", "equity,option"] = "equity,option",
    service: MarketService = Depends(market_service),
) -> SuccessEnvelope[list[MarketHours]]:
    normalized = tuple(markets.split(","))
    result = await service.market_hours(normalized, day)
    return envelope(request, result, filters={"markets": markets})
```

```python
# src/schwabber/schemas/status.py
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class TokenStatusView(BaseModel):
    state: Literal["OK", "URGENT", "EXPIRED", "MISSING", "UNAVAILABLE"]
    days_left: int | None
    expires_at: datetime | None


class ProviderReadiness(BaseModel):
    configured: bool
    ready: bool
    token: TokenStatusView


class ServiceStatus(BaseModel):
    version: str
    cache_available: bool
    schwab: ProviderReadiness
```

```python
# src/schwabber/api/status.py
from datetime import UTC, datetime

from fastapi import APIRouter, Request

from schwabber import __version__
from schwabber.schemas.common import CacheMeta, ResponseMeta, SuccessEnvelope
from schwabber.schemas.status import ProviderReadiness, ServiceStatus, TokenStatusView
from schwabber.token_status import TokenStatus, classify_token_file

router = APIRouter(prefix="/v1", tags=["service"])


@router.get(
    "/status",
    operation_id="get_service_status",
    response_model=SuccessEnvelope[ServiceStatus],
    response_model_exclude_none=True,
)
async def get_service_status(request: Request) -> SuccessEnvelope[ServiceStatus]:
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
    status = ServiceStatus(
        version=__version__,
        cache_available=True,
        schwab=ProviderReadiness(
            configured=settings.schwab_configured,
            ready=request.app.state.market_service is not None,
            token=TokenStatusView(
                state=token.state,
                days_left=token.days_left,
                expires_at=token.expires_at,
            ),
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
        ),
    )
```

```python
# src/schwabber/api/__init__.py
"""HTTP route modules."""
```

```python
# Replace src/schwabber/app.py
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials

from schwabber.api.market import router as market_router
from schwabber.api.status import router as status_router
from schwabber.auth import bearer, require_api_key
from schwabber.config import Settings
from schwabber.errors import AppError
from schwabber.services.market import MarketService


def build_app(
    settings: Settings,
    market_service: MarketService | None = None,
) -> FastAPI:
    app = FastAPI(title="Schwabber", version="0.1.0")
    app.state.settings = settings
    app.state.market_service = market_service

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    async def authorized(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> None:
        await require_api_key(request, credentials)

    def error_response(request: Request, exc: AppError) -> JSONResponse:
        response = JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "retryable": exc.retryable,
                    "retry_after_seconds": exc.retry_after_seconds,
                    "request_id": request.state.request_id,
                }
            },
        )
        if exc.retry_after_seconds is not None:
            response.headers["Retry-After"] = str(exc.retry_after_seconds)
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return error_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"][1:])
        message = f"Invalid {location}: {first['msg']}"
        from schwabber.errors import InvalidRequest

        return error_response(request, InvalidRequest(message))

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "alive"}

    dependencies = [Depends(authorized)]
    app.include_router(status_router, dependencies=dependencies)
    app.include_router(market_router, dependencies=dependencies)
    return app
```

- [ ] **Step 4: Run API and OpenAPI tests**

Run: `.venv/bin/pytest tests/test_market_api.py tests/test_openapi.py tests/test_response_budget.py -q`

Expected: `6 passed` and both serialized maximum-shape assertions are below
90,000 characters.

- [ ] **Step 5: Commit the API**

```bash
git add src/schwabber/api src/schwabber/schemas/status.py src/schwabber/app.py tests/test_market_api.py tests/test_openapi.py tests/test_response_budget.py
git commit -m "feat: expose Schwab research API"
```

### Task 13: Wire production client creation and live smoke checks

**Files:**
- Modify: `src/schwabber/providers/schwab.py`
- Modify: `src/schwabber/app.py`
- Modify: `src/schwabber/cli.py`
- Create: `tests/test_provider_factory.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_app.py`

- [ ] **Step 1: Write failing factory tests**

```python
# tests/test_provider_factory.py
from dataclasses import replace

import pytest

from schwabber.config import Settings
from schwabber.errors import SchwabReauthRequired
from schwabber.providers.schwab import create_schwab_provider


@pytest.mark.asyncio
async def test_missing_token_requires_reauthorization(tmp_path) -> None:
    settings = Settings.from_mapping(
        {
            "SCHWABBER_API_KEY": "k" * 32,
            "SCHWAB_CLIENT_ID": "client-id",
            "SCHWAB_CLIENT_SECRET": "client-secret",
        }
    )
    settings = replace(settings, token_path=tmp_path / "missing.json")
    with pytest.raises(SchwabReauthRequired):
        await create_schwab_provider(settings)
```

```python
# Add to tests/test_cli.py
import asyncio
from datetime import UTC, datetime

from schwabber.cli import smoke
from schwabber.config import Settings
from schwabber.schemas.market import Candle, Quote


def test_smoke_prints_counts_but_not_secrets(monkeypatch, capsys) -> None:
    class Provider:
        async def quotes(self, symbols):
            return [
                Quote(
                    symbol=symbols[0],
                    quote_time=datetime(2026, 8, 28, tzinfo=UTC),
                )
            ]

        async def history(self, symbol, start, end, frequency, extended):
            return [
                Candle(
                    timestamp=datetime(2026, 8, 28, tzinfo=UTC),
                    open=1.0,
                    high=2.0,
                    low=0.5,
                    close=1.5,
                    volume=100,
                )
            ]

    async def factory(settings):
        return Provider()

    monkeypatch.setattr("schwabber.cli.create_schwab_provider", factory)
    settings = Settings.from_mapping(
        {
            "SCHWABBER_API_KEY": "middleware-secret-" + "k" * 32,
            "SCHWAB_CLIENT_ID": "client-id",
            "SCHWAB_CLIENT_SECRET": "broker-secret",
        }
    )
    asyncio.run(smoke(settings, "amd"))
    output = capsys.readouterr().out
    assert '"symbol":"AMD"' in output
    assert '"quote_count":1' in output
    assert "broker-secret" not in output
    assert settings.api_key not in output
```

```python
# Add to tests/test_app.py
def test_lifespan_creates_one_schwab_client(monkeypatch, tmp_path) -> None:
    calls = 0

    async def factory(settings):
        nonlocal calls
        calls += 1
        return object()

    monkeypatch.setattr("schwabber.app.create_schwab_provider", factory)
    configured = Settings.from_mapping(
        {
            "SCHWABBER_API_KEY": "k" * 32,
            "SCHWAB_CLIENT_ID": "client-id",
            "SCHWAB_CLIENT_SECRET": "client-secret",
            "SCHWAB_TOKEN_PATH": str(tmp_path / "token.json"),
        }
    )
    with TestClient(build_app(configured)) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/healthz").status_code == 200
    assert calls == 1
```

- [ ] **Step 2: Run the factory tests to verify they fail**

Run: `.venv/bin/pytest tests/test_provider_factory.py tests/test_cli.py -q`

Expected: FAIL because `create_schwab_provider` is absent and smoke exits.

- [ ] **Step 3: Implement async client creation and smoke**

```python
# Add to src/schwabber/providers/schwab.py
import httpx

from schwabber.config import Settings
from schwabber.errors import SchwabReauthRequired


async def create_schwab_provider(settings: Settings) -> SchwabMarketProvider:
    if not settings.schwab_configured or not settings.token_path.exists():
        raise SchwabReauthRequired("Run: schwabber auth login")
    assert settings.schwab_client_id is not None
    assert settings.schwab_client_secret is not None
    try:
        from schwab.auth import client_from_token_file

        client = client_from_token_file(
            str(settings.token_path),
            settings.schwab_client_id,
            settings.schwab_client_secret,
            asyncio=True,
            enforce_enums=False,
        )
        client.set_timeout(httpx.Timeout(25.0, connect=3.0, read=10.0))
    except Exception as exc:
        raise SchwabReauthRequired("Run: schwabber auth login") from exc
    return SchwabMarketProvider(client)
```

```python
# Add these imports to src/schwabber/app.py
from contextlib import asynccontextmanager

from schwabber.cache import TtlLruCache
from schwabber.errors import SchwabReauthRequired
from schwabber.providers.schwab import create_schwab_provider


# Replace FastAPI construction inside build_app with this block. Keep the
# middleware, handlers, health route, and router registration from Task 12.
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.market_service is None and settings.schwab_configured:
            try:
                provider = await create_schwab_provider(settings)
            except SchwabReauthRequired:
                app.state.market_service = None
            else:
                app.state.market_service = MarketService(
                    provider,
                    TtlLruCache(max_entries=1024),
                )
        yield

    app = FastAPI(title="Schwabber", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.market_service = market_service


# Add after build_app.
def create_app() -> FastAPI:
    return build_app(Settings.from_env())
```

```python
# Add these imports and functions to src/schwabber/cli.py
import asyncio
import json
from datetime import date, timedelta

from schwabber.providers.schwab import create_schwab_provider


async def smoke(settings: Settings, symbol: str) -> None:
    normalized = symbol.upper()
    provider = await create_schwab_provider(settings)
    end = date.today()
    quotes = await provider.quotes((normalized,))
    candles = await provider.history(
        normalized,
        end - timedelta(days=5),
        end,
        "1d",
        False,
    )
    print(
        json.dumps(
            {
                "symbol": normalized,
                "provider_ready": True,
                "quote_count": len(quotes),
                "quote_timestamp": (
                    quotes[0].quote_time.isoformat()
                    if quotes and quotes[0].quote_time
                    else None
                ),
                "candle_count": len(candles),
                "latest_candle_timestamp": (
                    candles[-1].timestamp.isoformat() if candles else None
                ),
            },
            separators=(",", ":"),
        )
    )


# Insert before the final SystemExit in main().
    if args.command == "smoke":
        asyncio.run(smoke(settings, args.symbol))
        return
```

- [ ] **Step 4: Run factory and CLI tests**

Run: `.venv/bin/pytest tests/test_provider_factory.py tests/test_cli.py -q`

Expected: all tests PASS; the lifespan assertion reports one factory call and
the captured smoke output contains neither configured secret.

- [ ] **Step 5: Commit runtime wiring**

```bash
git add src/schwabber/providers/schwab.py src/schwabber/app.py src/schwabber/cli.py tests
git commit -m "feat: wire Schwab runtime and smoke checks"
```

### Task 14: Add Docker-first local operation and Phase 1 documentation

**Files:**
- Create: `Dockerfile`
- Create: `compose.yaml`
- Create: `.dockerignore`
- Create: `.env.example`
- Create: `README.md`
- Create: `tests/test_distribution.py`

- [ ] **Step 1: Write failing distribution checks**

```python
# tests/test_distribution.py
from pathlib import Path


def test_distribution_files_do_not_contain_secrets() -> None:
    example = Path(".env.example").read_text()
    assert "SCHWABBER_API_KEY=" in example
    assert "SCHWAB_CLIENT_SECRET=" in example
    assert "token.json" in Path(".gitignore").read_text()
    assert "/data" in Path("compose.yaml").read_text()
```

- [ ] **Step 2: Run the check to verify it fails**

Run: `.venv/bin/pytest tests/test_distribution.py -q`

Expected: FAIL because distribution files are absent.

- [ ] **Step 3: Add the local container setup**

```dockerfile
# Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
RUN useradd --create-home --uid 10001 schwabber
RUN mkdir /data && chown schwabber:schwabber /data
USER schwabber
EXPOSE 8000
CMD ["schwabber", "serve"]
```

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
    restart: unless-stopped

volumes:
  schwabber-data:
```

```dotenv
# .env.example
SCHWABBER_API_KEY=
SCHWAB_CLIENT_ID=
SCHWAB_CLIENT_SECRET=
SCHWAB_CALLBACK_URL=https://127.0.0.1:8182
SCHWAB_TOKEN_PATH=/data/token.json
SCHWAB_REFRESH_TOKEN_MAX_AGE_DAYS=7
SCHWAB_REFRESH_TOKEN_WARN_AGE_DAYS=6
SCHWABBER_REQUESTS_PER_MINUTE=60
SCHWABBER_LOG_LEVEL=INFO
SEC_USER_AGENT=
```

```gitignore
# .dockerignore
.env
.git/
.venv/
data/
token.json
**/__pycache__/
**/.pytest_cache/
docs/
tests/
```

````markdown
<!-- README.md -->
# Schwabber

Schwabber is a self-hosted, read-only market-data Action for a private Custom
GPT. It normalizes selected Schwab Trader API responses and never exposes
account, position, or order operations.

## Local setup

Requirements: Docker Compose, a Schwab developer application, and ngrok when
the Action must be reachable from ChatGPT.

```bash
cp .env.example .env
openssl rand -hex 32
```

Put the generated value in `SCHWABBER_API_KEY`, then set your Schwab client ID,
client secret, and exact registered callback URL in `.env`.

```bash
docker compose build
docker compose run --rm schwabber auth login
docker compose up -d
curl http://127.0.0.1:8000/healthz
```

The login command prints a Schwab authorization URL. Open it in a browser,
authorize, and paste the complete redirected URL back into the terminal. The
token is stored in the Docker volume, not in the repository.

## Connect a private GPT

```bash
ngrok http 8000
```

In ChatGPT, edit the private GPT, open **Actions**, and import
`https://YOUR-NGROK-HOST/openapi.json`. Choose API-key authentication, select
Bearer, and enter the same `SCHWABBER_API_KEY` value. Keep ChatGPT web search
enabled for current news; Schwabber does not provide or scrape a news feed.

Protected requests use:

```bash
curl -H "Authorization: Bearer YOUR_KEY" \
  "https://YOUR-NGROK-HOST/v1/quotes?symbols=AAPL,MSFT"
```

Phase 1 includes Schwab quotes, price history, instrument fundamentals,
options, movers, market hours, and token status. SEC financials and filings
are added in Phase 2.

## Security boundary

Run one application worker. Never commit `.env`, `/data/token.json`, logs, or
real provider responses. This software supplies research data and does not
provide investment advice or execute trades.
````

- [ ] **Step 4: Verify tests and image**

Run: `.venv/bin/pytest -q`

Expected: all tests pass.

Run: `.venv/bin/ruff check .`

Expected: `All checks passed!`

Run: `.venv/bin/mypy src`

Expected: `Success: no issues found`.

Run: `docker build -t schwabber:phase1 .`

Expected: Docker exits zero and tags `schwabber:phase1`.

- [ ] **Step 5: Commit Phase 1 distribution**

```bash
git add Dockerfile compose.yaml .dockerignore .env.example README.md tests/test_distribution.py
git commit -m "docs: add local Schwabber deployment"
```

## Phase 1 completion gate

Run:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/mypy src
docker build -t schwabber:phase1 .
docker compose config
```

Expected:

- Every command exits zero.
- The complete test suite has no skips except tests explicitly marked
  `live_schwab`.
- The OpenAPI document contains the seven protected read-only market/status
  operations and no account or order operation.
- Maximum synthetic history and option responses serialize below 90,000
  characters.
- The service starts and returns `200 {"status":"alive"}` without a Schwab
  token, while protected Schwab routes return the documented compact `503`.
