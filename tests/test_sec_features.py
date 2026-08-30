
import httpx
import pytest

from schwabber.cache import TtlLruCache
from schwabber.providers.sec import HttpSecProvider
from schwabber.sec_normalizer import normalize_filings, normalize_financials
from schwabber.services.sec import SecResearchService


@pytest.mark.asyncio
async def test_sec_provider_zero_pads_cik() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"0": {"cik_str": 2488, "ticker": "AMD"}}, request=request
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = HttpSecProvider(client, "operator@example.com")
    assert await provider.cik_for_symbol("amd") == "0000002488"
    await client.aclose()


def test_sec_filing_normalization_builds_archive_url() -> None:
    payload = {
        "filings": {
            "recent": {
                "accessionNumber": ["0000002488-26-000001"],
                "filingDate": ["2026-08-20"],
                "reportDate": ["2026-06-30"],
                "form": ["10-Q"],
                "primaryDocument": ["report.htm"],
                "primaryDocDescription": ["Quarterly"],
            }
        }
    }
    filing = normalize_filings(payload, cik="0000002488", forms={"10-Q"}, limit=1)[0]
    assert filing.url.endswith("/2488/000000248826000001/report.htm")


def test_annual_comparatives_are_deduplicated_by_period_end() -> None:
    def fact(fy, filed, value, accession=None):
        return {
            "start": f"{fy}-01-01",
            "end": f"{fy}-12-31",
            "val": value,
            "accn": accession or f"a{filed}",
            "fy": fy,
            "fp": "FY",
            "form": "10-K",
            "filed": filed,
        }

    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            fact(2024, "2025-01-01", 390),
                            fact(2025, "2026-01-01", 420),
                            fact(2024, "2026-01-01", 390, "comparative"),
                        ]
                    }
                }
            }
        }
    }
    statement = normalize_financials(
        payload, symbol="AAPL", cik="0000320193", period_type="annual", count=5
    )
    assert len(statement.periods) == 2
    assert [period.fiscal_year for period in statement.periods] == [2025, 2024]


@pytest.mark.asyncio
async def test_sec_service_reuses_cik_lookup() -> None:
    class Provider:
        calls = 0

        async def cik_for_symbol(self, symbol):
            self.calls += 1
            return "0000002488"

        async def company_facts(self, cik):
            return {"facts": {}}

        async def submissions(self, cik):
            return {
                "filings": {
                    "recent": {
                        "accessionNumber": [],
                        "filingDate": [],
                        "reportDate": [],
                        "form": [],
                        "primaryDocument": [],
                        "primaryDocDescription": [],
                    }
                }
            }

    provider = Provider()
    service = SecResearchService(provider, TtlLruCache())
    await service.financials("AMD", "annual", 2)
    await service.financials("AMD", "annual", 2)
    assert provider.calls == 1
