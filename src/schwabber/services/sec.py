from datetime import UTC, datetime
from typing import Literal, cast

from schwabber.cache import TtlLruCache
from schwabber.errors import InvalidRequest
from schwabber.providers.sec import SecProvider
from schwabber.schemas.sec import Filing, FinancialStatement
from schwabber.sec_normalizer import normalize_filings, normalize_financials
from schwabber.services.market import ServiceResult


class SecResearchService:
    def __init__(
        self, provider: SecProvider, cache: TtlLruCache[tuple[object, ...], object]
    ) -> None:
        self._provider, self._cache = provider, cache

    async def _cik(self, symbol: str) -> str:
        key = ("sec_cik", symbol)
        cached = self._cache.get(key)
        if cached:
            return cast(str, cached[0])
        cik = await self._provider.cik_for_symbol(symbol)
        self._cache.set(key, cik, 86400)
        return cik

    async def financials(
        self, symbol: str, period_type: Literal["annual", "quarterly"], count: int
    ) -> ServiceResult[FinancialStatement]:
        if not 1 <= count <= 20:
            raise InvalidRequest("financial period count must be between 1 and 20")
        symbol = symbol.upper()
        key = ("sec_financials", symbol, period_type, count)
        cached = self._cache.get(key)
        if cached:
            r, age = cast(ServiceResult[FinancialStatement], cached[0]), cached[1]
            return ServiceResult(r.data, r.retrieved_at, True, age)
        cik = await self._cik(symbol)
        statement = normalize_financials(
            await self._provider.company_facts(cik),
            symbol=symbol,
            cik=cik,
            period_type=period_type,
            count=count,
        )
        result = ServiceResult(statement, datetime.now(UTC), False, 0)
        self._cache.set(key, result, 3600)
        return result

    async def filings(
        self, symbol: str, forms: tuple[str, ...], count: int
    ) -> ServiceResult[list[Filing]]:
        if not 1 <= count <= 100:
            raise InvalidRequest("filing count must be between 1 and 100")
        allowed = {"10-K", "10-Q", "8-K", "20-F", "6-K"}
        if not forms or not set(forms) <= allowed:
            raise InvalidRequest("forms contain an unsupported SEC form")
        symbol = symbol.upper()
        key = ("sec_filings", symbol, *forms, count)
        cached = self._cache.get(key)
        if cached:
            r, age = cast(ServiceResult[list[Filing]], cached[0]), cached[1]
            return ServiceResult(r.data, r.retrieved_at, True, age)
        cik = await self._cik(symbol)
        filings = normalize_filings(
            await self._provider.submissions(cik),
            cik=cik,
            forms=set(forms),
            limit=count,
        )
        result = ServiceResult(filings, datetime.now(UTC), False, 0)
        self._cache.set(key, result, 300)
        return result
