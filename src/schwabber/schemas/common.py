from datetime import datetime
from typing import Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class CacheMeta(BaseModel):
    hit: bool = Field(description="Whether Schwabber reused a cached result.")
    age_seconds: int = Field(
        description="Whole seconds since the cached result was first retrieved."
    )


class ResponseMeta(BaseModel):
    source: Literal["schwab", "sec", "application"] = Field(
        description="System that supplied the response data."
    )
    retrieved_at: datetime = Field(
        description="UTC time when Schwabber assembled the underlying result."
    )
    request_id: str
    cache: CacheMeta = Field(description="Cache reuse and age for this result.")
    result_count: int | None = None
    truncated: bool = Field(
        default=False,
        description="Whether a configured or upstream bound shortened the result.",
    )
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
