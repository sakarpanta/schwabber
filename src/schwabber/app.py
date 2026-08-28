from contextlib import asynccontextmanager
from uuid import uuid4

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
from schwabber.services.market import MarketService


def build_app(
    settings: Settings, market_service: MarketService | None = None
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
        yield

    app = FastAPI(
        title="Schwabber",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
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
    return app


def create_app() -> FastAPI:
    return build_app(Settings.from_env())
