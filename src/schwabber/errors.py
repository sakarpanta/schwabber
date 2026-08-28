class AppError(Exception):
    status_code = 500
    code = "INTERNAL_ERROR"
    retryable = False

    def __init__(self, message: str, retry_after_seconds: int | None = None) -> None:
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
