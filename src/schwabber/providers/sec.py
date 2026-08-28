import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import httpx

from schwabber.errors import ResourceNotFound, UpstreamFailure
from schwabber.rate_limit import TokenBucket
from schwabber.retry import retry_async

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


class SecProvider(Protocol):
    async def cik_for_symbol(self, symbol: str) -> str: ...
    async def submissions(self, cik: str) -> dict[str, Any]: ...
    async def company_facts(self, cik: str) -> dict[str, Any]: ...


class _TransientSecError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


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
        self._headers = {"User-Agent": user_agent, "Accept": "application/json"}

    async def _get(self, url: str) -> dict[str, Any]:
        async def attempt() -> httpx.Response:
            wait = self._fair_access.consume("sec")
            if wait is not None:
                await self._sleep(float(wait))
            response = await self._client.get(url, headers=self._headers)
            if response.status_code == 429 or response.status_code >= 500:
                raise _TransientSecError(response.status_code)
            return response

        try:
            response = await retry_async(
                attempt,
                should_retry=lambda exc: isinstance(exc, _TransientSecError),
                sleep=self._sleep,
            )
        except _TransientSecError as exc:
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

    async def cik_for_symbol(self, symbol: str) -> str:
        normalized = symbol.upper()
        payload = await self._get(TICKERS_URL)
        for item in payload.values():
            if (
                isinstance(item, dict)
                and str(item.get("ticker", "")).upper() == normalized
            ):
                return f"{int(item['cik_str']):010d}"
        raise ResourceNotFound(f"No SEC registrant found for {normalized}")

    async def submissions(self, cik: str) -> dict[str, Any]:
        return await self._get(SUBMISSIONS_URL.format(cik=cik))

    async def company_facts(self, cik: str) -> dict[str, Any]:
        return await self._get(FACTS_URL.format(cik=cik))
