from datetime import datetime
from typing import Literal, TypeVar

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


class SuccessEnvelope[T](BaseModel):
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
