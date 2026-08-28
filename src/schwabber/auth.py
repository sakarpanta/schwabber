import hmac
import ipaddress

from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from schwabber.errors import RateLimited, Unauthorized

bearer = HTTPBearer(auto_error=False)


async def require_api_key(
    request: Request, credentials: HTTPAuthorizationCredentials | None
) -> None:
    supplied = credentials.credentials if credentials else ""
    expected = request.app.state.settings.api_key
    direct = request.client.host if request.client else "unknown"
    try:
        trusted = ipaddress.ip_address(direct).is_loopback
    except ValueError:
        trusted = False
    forwarded = request.headers.get("X-Forwarded-For")
    client_ip = forwarded.split(",", 1)[0].strip() if trusted and forwarded else direct
    request.app.state.last_auth_client_ip = client_ip
    if not hmac.compare_digest(supplied, expected):
        retry = request.app.state.invalid_auth_limiter.consume(client_ip)
        if retry is not None:
            raise RateLimited("Too many invalid authentication attempts", retry)
        raise Unauthorized("Missing or invalid API key")
    retry = request.app.state.authenticated_limiter.consume("operator")
    if retry is not None:
        raise RateLimited("Middleware request limit exceeded", retry)
