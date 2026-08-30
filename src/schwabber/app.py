from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials

from schwabber.api.market import router as market_router
from schwabber.api.status import router as status_router
from schwabber.auth import bearer, require_api_key
from schwabber.cache import TtlLruCache
from schwabber.config import Settings
from schwabber.errors import AppError, InvalidRequest, SchwabReauthRequired
from schwabber.providers.schwab import create_schwab_provider
from schwabber.providers.sec import HttpSecProvider
from schwabber.services.market import MarketService
from schwabber.services.sec import SecResearchService


def build_app(
    settings: Settings,
    market_service: MarketService | None = None,
    sec_service: SecResearchService | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.market_service is None and settings.schwab_configured:
            try:
                provider = await create_schwab_provider(settings)
            except SchwabReauthRequired:
                provider = None
            if provider is not None:
                app.state.market_service = MarketService(provider, TtlLruCache())
        if app.state.sec_service is None and settings.sec_configured:
            client = httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=3.0))
            app.state.sec_client = client
            app.state.sec_service = SecResearchService(
                HttpSecProvider(client, settings.sec_user_agent or ""), TtlLruCache()
            )
        yield
        if getattr(app.state, "sec_client", None) is not None:
            await app.state.sec_client.aclose()

    app = FastAPI(
        title="Schwabber",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        servers=[{"url": settings.public_base_url}],
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.market_service = market_service
    app.state.sec_service = sec_service

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

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
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

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(item) for item in first.get("loc", []))
        message = f"Invalid value for {location}" if location else "Invalid request"
        return await app_error_handler(request, InvalidRequest(message))

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "alive"}

    dependencies = [Depends(authorized)]
    app.include_router(status_router, dependencies=dependencies)
    app.include_router(market_router, dependencies=dependencies)
    from schwabber.api.sec import router as sec_router

    app.include_router(sec_router, dependencies=dependencies)
    return app


def create_app() -> FastAPI:
    return build_app(Settings.from_env())
