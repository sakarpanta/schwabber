import hmac

from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from schwabber.errors import Unauthorized

bearer = HTTPBearer(auto_error=False)


async def require_api_key(
    request: Request, credentials: HTTPAuthorizationCredentials | None
) -> None:
    supplied = credentials.credentials if credentials else ""
    expected = request.app.state.settings.api_key
    if not hmac.compare_digest(supplied, expected):
        raise Unauthorized("Missing or invalid API key")
