# Phase 2: SEC Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add bounded recent-filing metadata and provenance-rich annual or directly reported quarterly financial series from SEC EDGAR without weakening the Phase 1 Schwab Action.

**Architecture:** A dedicated async SEC adapter retrieves ticker mappings, submissions, and company facts; pure normalizers convert those payloads into stable domain models. `SecResearchService` owns SEC-specific caching and limits, and its routes remain available when Schwab is degraded.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic, httpx, pytest, pytest-asyncio, synthetic SEC JSON fixtures

---

## File map

- `src/schwabber/config.py`: add SEC identity configuration and readiness.
- `src/schwabber/schemas/sec.py`: filing and financial response models.
- `src/schwabber/providers/sec.py`: SEC HTTP transport and ticker-to-CIK lookup.
- `src/schwabber/sec_concepts.py`: ordered canonical metric aliases and units.
- `src/schwabber/sec_normalizer.py`: pure filing and company-fact normalization.
- `src/schwabber/services/sec.py`: cache, bounds, and SEC orchestration.
- `src/schwabber/api/sec.py`: protected financial and filing routes.
- `src/schwabber/api/dependencies.py`: SEC service dependency.
- `src/schwabber/api/status.py`: SEC readiness in service status.
- `src/schwabber/app.py`: one shared SEC HTTP client in the application lifespan.
- `tests/fixtures/sec/`: synthetic ticker, submissions, and company-facts payloads.
- `tests/`: offline unit, route, outage-isolation, and size-budget tests.

### Task 1: Add SEC configuration and response models

**Files:**
- Modify: `src/schwabber/config.py`
- Create: `src/schwabber/schemas/sec.py`
- Modify: `src/schwabber/schemas/status.py`
- Modify: `tests/test_config.py`
- Create: `tests/test_sec_schemas.py`

- [ ] **Step 1: Write failing configuration and provenance tests**

```python
# Add to tests/test_config.py
def test_sec_is_configured_only_with_descriptive_user_agent() -> None:
    missing = Settings.from_mapping({"SCHWABBER_API_KEY": "k" * 32})
    configured = Settings.from_mapping(
        {
            "SCHWABBER_API_KEY": "k" * 32,
            "SEC_USER_AGENT": "Schwabber operator@example.com",
        }
    )
    assert missing.sec_configured is False
    assert configured.sec_configured is True
```

```python
# tests/test_sec_schemas.py
from datetime import date

from schwabber.schemas.sec import FinancialFact


def test_financial_fact_keeps_full_provenance() -> None:
    fact = FinancialFact(
        value=1_000_000.0,
        taxonomy="us-gaap",
        concept="Revenues",
        unit="USD",
        start=date(2025, 1, 1),
        end=date(2025, 12, 31),
        fiscal_year=2025,
        fiscal_period="FY",
        form="10-K",
        filed=date(2026, 2, 15),
        accession_number="0000000000-26-000001",
        reported=True,
        derived_from=[],
    )
    assert fact.reported is True
    assert fact.accession_number.endswith("000001")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_config.py tests/test_sec_schemas.py -q`

Expected: FAIL because SEC settings and schemas are absent.

- [ ] **Step 3: Extend settings and add normalized models**

```python
# Add this field to Settings in src/schwabber/config.py
    sec_user_agent: str | None

# Add this property below schwab_configured.
    @property
    def sec_configured(self) -> bool:
        return bool(self.sec_user_agent and "@" in self.sec_user_agent)

# Add this keyword inside the Settings(...) return in from_mapping().
            sec_user_agent=values.get("SEC_USER_AGENT") or None,
```

```python
# src/schwabber/schemas/sec.py
from datetime import date
from typing import Literal

from pydantic import BaseModel


class Filing(BaseModel):
    form: str
    filing_date: date
    report_date: date | None = None
    accession_number: str
    description: str | None = None
    primary_document: str
    url: str


class FinancialFact(BaseModel):
    value: float
    taxonomy: str
    concept: str
    unit: str
    start: date | None = None
    end: date
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    form: str
    filed: date
    accession_number: str
    reported: bool
    derived_from: list[str]


class FinancialPeriod(BaseModel):
    fiscal_year: int | None
    fiscal_period: str | None
    period_end: date
    form: str
    filed: date
    accession_number: str
    metrics: dict[str, FinancialFact | None]


class FinancialStatement(BaseModel):
    symbol: str
    cik: str
    period_type: Literal["annual", "quarterly"]
    periods: list[FinancialPeriod]
```

```python
# Replace ProviderReadiness and ServiceStatus in src/schwabber/schemas/status.py
class ProviderReadiness(BaseModel):
    configured: bool
    ready: bool


class SchwabReadiness(ProviderReadiness):
    token: TokenStatusView


class ServiceStatus(BaseModel):
    version: str
    cache_available: bool
    schwab: SchwabReadiness
    sec: ProviderReadiness
```

- [ ] **Step 4: Run configuration and schema tests**

Run: `.venv/bin/pytest tests/test_config.py tests/test_sec_schemas.py -q`

Expected: all tests PASS.

- [ ] **Step 5: Commit SEC configuration and models**

```bash
git add src/schwabber/config.py src/schwabber/schemas tests/test_config.py tests/test_sec_schemas.py
git commit -m "feat: define SEC research contracts"
```

### Task 2: Implement the SEC HTTP adapter and CIK lookup

**Files:**
- Create: `src/schwabber/providers/sec.py`
- Create: `tests/fixtures/sec/company_tickers.json`
- Create: `tests/test_sec_provider.py`

- [ ] **Step 1: Add a synthetic ticker map and failing adapter tests**

**`tests/fixtures/sec/company_tickers.json`:**

```json
{
  "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
  "1": {"cik_str": 2488, "ticker": "AMD", "title": "Synthetic AMD Inc."}
}
```

```python
# tests/test_sec_provider.py
import json
from pathlib import Path

import httpx
import pytest

from schwabber.errors import ResourceNotFound
from schwabber.providers.sec import HttpSecProvider


def response(url: str, body: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json=body,
        request=httpx.Request("GET", url),
    )


@pytest.mark.asyncio
async def test_cik_lookup_is_case_insensitive_and_zero_padded() -> None:
    body = json.loads(Path("tests/fixtures/sec/company_tickers.json").read_text())

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"] == "Schwabber operator@example.com"
        return response(str(request.url), body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = HttpSecProvider(client, "Schwabber operator@example.com")
    assert await provider.cik_for_symbol("amd") == "0000002488"
    await client.aclose()


@pytest.mark.asyncio
async def test_unknown_ticker_raises_not_found() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return response(str(request.url), {})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = HttpSecProvider(client, "Schwabber operator@example.com")
    with pytest.raises(ResourceNotFound, match="UNKNOWN"):
        await provider.cik_for_symbol("UNKNOWN")
    await client.aclose()
```

- [ ] **Step 2: Run adapter tests to verify they fail**

Run: `.venv/bin/pytest tests/test_sec_provider.py -q`

Expected: FAIL because `HttpSecProvider` is absent.

- [ ] **Step 3: Implement bounded JSON requests and lookup**

```python
# src/schwabber/providers/sec.py
from typing import Any, Protocol

import httpx

from schwabber.errors import ResourceNotFound, UpstreamFailure

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


class SecProvider(Protocol):
    async def cik_for_symbol(self, symbol: str) -> str: ...
    async def submissions(self, cik: str) -> dict[str, Any]: ...
    async def company_facts(self, cik: str) -> dict[str, Any]: ...


class HttpSecProvider:
    def __init__(self, client: httpx.AsyncClient, user_agent: str) -> None:
        self._client = client
        self._headers = {
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json",
        }

    async def _get(self, url: str) -> dict[str, Any]:
        response = await self._client.get(url, headers=self._headers)
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
            if isinstance(item, dict) and item.get("ticker", "").upper() == normalized:
                return f"{int(item['cik_str']):010d}"
        raise ResourceNotFound(f"No SEC registrant found for {normalized}")

    async def submissions(self, cik: str) -> dict[str, Any]:
        return await self._get(SUBMISSIONS_URL.format(cik=cik))

    async def company_facts(self, cik: str) -> dict[str, Any]:
        return await self._get(FACTS_URL.format(cik=cik))
```

- [ ] **Step 4: Run provider tests**

Run: `.venv/bin/pytest tests/test_sec_provider.py -q`

Expected: `2 passed`.

- [ ] **Step 5: Commit the adapter**

```bash
git add src/schwabber/providers/sec.py tests/fixtures/sec/company_tickers.json tests/test_sec_provider.py
git commit -m "feat: add SEC data adapter"
```

### Task 3: Normalize recent filing metadata

**Files:**
- Create: `tests/fixtures/sec/submissions.json`
- Create: `src/schwabber/sec_normalizer.py`
- Create: `tests/test_sec_filings.py`

- [ ] **Step 1: Add a synthetic submissions fixture and failing test**

**`tests/fixtures/sec/submissions.json`:**

```json
{
  "cik": "0000002488",
  "filings": {
    "recent": {
      "accessionNumber": ["0000002488-26-000010", "0000002488-26-000009"],
      "filingDate": ["2026-08-20", "2026-08-01"],
      "reportDate": ["2026-08-19", "2026-06-30"],
      "form": ["8-K", "10-Q"],
      "primaryDocument": ["amd-20260819.htm", "amd-20260630.htm"],
      "primaryDocDescription": ["Current report", "Quarterly report"]
    }
  }
}
```

```python
# tests/test_sec_filings.py
import json
from pathlib import Path

from schwabber.sec_normalizer import normalize_filings


def test_filings_are_filtered_bounded_and_linked_to_sec() -> None:
    body = json.loads(Path("tests/fixtures/sec/submissions.json").read_text())
    filings = normalize_filings(
        body,
        cik="0000002488",
        forms={"10-Q"},
        limit=1,
    )
    assert len(filings) == 1
    assert filings[0].form == "10-Q"
    assert filings[0].url.startswith("https://www.sec.gov/Archives/edgar/data/2488/")
```

- [ ] **Step 2: Run the filing test to verify it fails**

Run: `.venv/bin/pytest tests/test_sec_filings.py -q`

Expected: FAIL because `normalize_filings` is absent.

- [ ] **Step 3: Implement filing normalization**

```python
# src/schwabber/sec_normalizer.py
from datetime import date
from typing import Any

from schwabber.errors import UpstreamFailure
from schwabber.schemas.sec import Filing


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def normalize_filings(
    payload: dict[str, Any],
    *,
    cik: str,
    forms: set[str],
    limit: int,
) -> list[Filing]:
    recent = payload.get("filings", {}).get("recent", {})
    required = (
        "accessionNumber",
        "filingDate",
        "reportDate",
        "form",
        "primaryDocument",
        "primaryDocDescription",
    )
    columns = [recent.get(name) for name in required]
    if not all(isinstance(column, list) for column in columns):
        raise UpstreamFailure("SEC submissions response is missing recent filings")
    if len({len(column) for column in columns}) != 1:
        raise UpstreamFailure("SEC submissions columns have inconsistent lengths")
    results: list[Filing] = []
    for values in zip(*columns, strict=True):
        accession, filing_date, report_date, form, document, description = values
        if form not in forms:
            continue
        accession_path = str(accession).replace("-", "")
        url = (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{int(cik)}/{accession_path}/{document}"
        )
        results.append(
            Filing(
                form=form,
                filing_date=date.fromisoformat(filing_date),
                report_date=_parse_date(report_date),
                accession_number=accession,
                description=description or None,
                primary_document=document,
                url=url,
            )
        )
        if len(results) == limit:
            break
    return results
```

- [ ] **Step 4: Run the filing test**

Run: `.venv/bin/pytest tests/test_sec_filings.py -q`

Expected: `1 passed`.

- [ ] **Step 5: Commit filing normalization**

```bash
git add src/schwabber/sec_normalizer.py tests/fixtures/sec/submissions.json tests/test_sec_filings.py
git commit -m "feat: normalize SEC filing metadata"
```

### Task 4: Define explicit financial concept aliases

**Files:**
- Create: `src/schwabber/sec_concepts.py`
- Create: `tests/test_sec_concepts.py`

- [ ] **Step 1: Write failing catalog tests**

```python
# tests/test_sec_concepts.py
from schwabber.sec_concepts import CONCEPTS


def test_catalog_has_ordered_us_gaap_and_ifrs_revenue_aliases() -> None:
    revenue = CONCEPTS["revenue"]
    assert revenue.unit == "USD"
    assert revenue.duration is True
    assert revenue.aliases[0] == (
        "us-gaap",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
    )
    assert ("ifrs-full", "Revenue") in revenue.aliases


def test_catalog_does_not_include_custom_taxonomy_wildcards() -> None:
    assert all(
        taxonomy in {"us-gaap", "ifrs-full"}
        for definition in CONCEPTS.values()
        for taxonomy, _ in definition.aliases
    )
```

- [ ] **Step 2: Run the catalog tests to verify they fail**

Run: `.venv/bin/pytest tests/test_sec_concepts.py -q`

Expected: FAIL because the catalog is absent.

- [ ] **Step 3: Add the ordered catalog**

```python
# src/schwabber/sec_concepts.py
from dataclasses import dataclass


@dataclass(frozen=True)
class ConceptDefinition:
    unit: str
    duration: bool
    aliases: tuple[tuple[str, str], ...]


CONCEPTS: dict[str, ConceptDefinition] = {
    "revenue": ConceptDefinition(
        "USD",
        True,
        (
            ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
            ("us-gaap", "Revenues"),
            ("us-gaap", "SalesRevenueNet"),
            ("ifrs-full", "Revenue"),
        ),
    ),
    "net_income": ConceptDefinition(
        "USD",
        True,
        (("us-gaap", "NetIncomeLoss"), ("ifrs-full", "ProfitLoss")),
    ),
    "diluted_eps": ConceptDefinition(
        "USD/shares",
        True,
        (
            ("us-gaap", "EarningsPerShareDiluted"),
            ("us-gaap", "DilutedEarningsLossPerShare"),
            ("ifrs-full", "DilutedEarningsLossPerShare"),
        ),
    ),
    "assets": ConceptDefinition(
        "USD", False, (("us-gaap", "Assets"), ("ifrs-full", "Assets"))
    ),
    "liabilities": ConceptDefinition(
        "USD",
        False,
        (("us-gaap", "Liabilities"), ("ifrs-full", "Liabilities")),
    ),
    "stockholders_equity": ConceptDefinition(
        "USD",
        False,
        (
            ("us-gaap", "StockholdersEquity"),
            (
                "us-gaap",
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            ),
            ("ifrs-full", "Equity"),
        ),
    ),
    "cash": ConceptDefinition(
        "USD",
        False,
        (
            ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
            (
                "us-gaap",
                "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
            ),
            ("ifrs-full", "CashAndCashEquivalents"),
        ),
    ),
    "short_term_debt": ConceptDefinition(
        "USD",
        False,
        (
            ("us-gaap", "ShortTermBorrowings"),
            ("us-gaap", "LongTermDebtCurrent"),
        ),
    ),
    "long_term_debt": ConceptDefinition(
        "USD",
        False,
        (
            ("us-gaap", "LongTermDebtNoncurrent"),
            ("us-gaap", "LongTermDebt"),
        ),
    ),
    "operating_cash_flow": ConceptDefinition(
        "USD",
        True,
        (
            ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
            ("ifrs-full", "CashFlowsFromUsedInOperatingActivities"),
        ),
    ),
    "capital_expenditure": ConceptDefinition(
        "USD",
        True,
        (
            ("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment"),
            ("ifrs-full", "PurchaseOfPropertyPlantAndEquipment"),
        ),
    ),
}
```

- [ ] **Step 4: Run catalog tests**

Run: `.venv/bin/pytest tests/test_sec_concepts.py -q`

Expected: `2 passed`.

- [ ] **Step 5: Commit the catalog**

```bash
git add src/schwabber/sec_concepts.py tests/test_sec_concepts.py
git commit -m "feat: define SEC financial concept catalog"
```

### Task 5: Select annual and directly reported quarterly facts

**Files:**
- Create: `tests/fixtures/sec/company_facts.json`
- Modify: `src/schwabber/sec_normalizer.py`
- Create: `tests/test_sec_financials.py`

- [ ] **Step 1: Add edge-case candidates and failing selection tests**

**`tests/fixtures/sec/company_facts.json`:**

```json
{
  "cik": 2488,
  "entityName": "Synthetic AMD Inc.",
  "facts": {
    "us-gaap": {
      "Revenues": {
        "units": {
          "USD": [
            {"start": "2025-01-01", "end": "2025-12-31", "val": 1000, "accn": "0000002488-26-000001", "fy": 2025, "fp": "FY", "form": "10-K", "filed": "2026-02-01"},
            {"start": "2025-01-01", "end": "2025-12-31", "val": 1010, "accn": "0000002488-26-000002", "fy": 2025, "fp": "FY", "form": "10-K/A", "filed": "2026-03-01"},
            {"start": "2026-01-01", "end": "2026-03-31", "val": 300, "accn": "0000002488-26-000010", "fy": 2026, "fp": "Q1", "form": "10-Q", "filed": "2026-05-01"},
            {"start": "2026-01-01", "end": "2026-06-30", "val": 650, "accn": "0000002488-26-000020", "fy": 2026, "fp": "Q2", "form": "10-Q", "filed": "2026-08-01"}
          ]
        }
      },
      "NetCashProvidedByUsedInOperatingActivities": {
        "units": {"USD": [{"start": "2025-01-01", "end": "2025-12-31", "val": 220, "accn": "0000002488-26-000002", "fy": 2025, "fp": "FY", "form": "10-K/A", "filed": "2026-03-01"}]}
      },
      "PaymentsToAcquirePropertyPlantAndEquipment": {
        "units": {"USD": [{"start": "2025-01-01", "end": "2025-12-31", "val": 70, "accn": "0000002488-26-000002", "fy": 2025, "fp": "FY", "form": "10-K/A", "filed": "2026-03-01"}]}
      },
      "Assets": {
        "units": {"USD": [{"end": "2025-12-31", "val": 5000, "accn": "0000002488-26-000002", "fy": 2025, "fp": "FY", "form": "10-K/A", "filed": "2026-03-01"}]}
      }
    }
  }
}
```

```python
# tests/test_sec_financials.py
from copy import deepcopy
import json
from pathlib import Path

from schwabber.sec_normalizer import normalize_financials


def payload() -> dict:
    return json.loads(Path("tests/fixtures/sec/company_facts.json").read_text())


def test_annual_selection_prefers_latest_amendment() -> None:
    statement = normalize_financials(
        payload(), symbol="AMD", cik="0000002488", period_type="annual", count=5
    )
    revenue = statement.periods[0].metrics["revenue"]
    assert revenue is not None
    assert revenue.value == 1010
    assert revenue.form == "10-K/A"


def test_quarterly_selection_rejects_year_to_date_duration() -> None:
    statement = normalize_financials(
        payload(), symbol="AMD", cik="0000002488", period_type="quarterly", count=8
    )
    assert len(statement.periods) == 1
    assert statement.periods[0].fiscal_period == "Q1"


def test_conflicting_aliases_return_null_instead_of_guessing() -> None:
    body = deepcopy(payload())
    body["facts"]["us-gaap"][
        "RevenueFromContractWithCustomerExcludingAssessedTax"
    ] = {
        "units": {
            "USD": [
                {
                    "start": "2025-01-01",
                    "end": "2025-12-31",
                    "val": 999,
                    "accn": "0000002488-26-000002",
                    "fy": 2025,
                    "fp": "FY",
                    "form": "10-K/A",
                    "filed": "2026-03-01"
                }
            ]
        }
    }
    statement = normalize_financials(
        body, symbol="AMD", cik="0000002488", period_type="annual", count=5
    )
    assert statement.periods[0].metrics["revenue"] is None
```

- [ ] **Step 2: Run the selection tests to verify they fail**

Run: `.venv/bin/pytest tests/test_sec_financials.py -q`

Expected: FAIL because financial normalization is absent.

- [ ] **Step 3: Implement deterministic candidate selection**

```python
# Add to src/schwabber/sec_normalizer.py
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from schwabber.schemas.sec import FinancialFact, FinancialPeriod, FinancialStatement
from schwabber.sec_concepts import CONCEPTS, ConceptDefinition


@dataclass(frozen=True)
class _Candidate:
    metric: str
    alias_rank: int
    value: float
    taxonomy: str
    concept: str
    unit: str
    start: date | None
    end: date
    fiscal_year: int | None
    fiscal_period: str | None
    form: str
    filed: date
    accession_number: str

    @property
    def context(self) -> tuple[object, ...]:
        return (
            self.start,
            self.end,
            self.fiscal_year,
            self.fiscal_period,
            self.unit,
        )


def _matches_period(
    item: dict[str, Any],
    definition: ConceptDefinition,
    period_type: Literal["annual", "quarterly"],
) -> bool:
    form = item.get("form")
    fiscal_period = item.get("fp")
    if period_type == "annual":
        if form not in {"10-K", "10-K/A", "20-F", "20-F/A"}:
            return False
        if fiscal_period != "FY":
            return False
    else:
        if form not in {"10-Q", "10-Q/A", "6-K", "6-K/A"}:
            return False
        if fiscal_period not in {"Q1", "Q2", "Q3"}:
            return False
    if not definition.duration:
        return True
    start = _parse_date(item.get("start"))
    end = _parse_date(item.get("end"))
    if start is None or end is None:
        return False
    duration = (end - start).days + 1
    return 300 <= duration <= 430 if period_type == "annual" else 70 <= duration <= 120


def _extract_candidates(
    payload: dict[str, Any],
    period_type: Literal["annual", "quarterly"],
) -> list[_Candidate]:
    facts = payload.get("facts", {})
    candidates: list[_Candidate] = []
    for metric, definition in CONCEPTS.items():
        for alias_rank, (taxonomy, concept) in enumerate(definition.aliases):
            concept_body = facts.get(taxonomy, {}).get(concept, {})
            records = concept_body.get("units", {}).get(definition.unit, [])
            if not isinstance(records, list):
                continue
            for item in records:
                if not isinstance(item, dict) or not _matches_period(
                    item, definition, period_type
                ):
                    continue
                end = _parse_date(item.get("end"))
                filed = _parse_date(item.get("filed"))
                if end is None or filed is None:
                    continue
                value = item.get("val")
                if not isinstance(value, int | float):
                    continue
                candidates.append(
                    _Candidate(
                        metric=metric,
                        alias_rank=alias_rank,
                        value=float(value),
                        taxonomy=taxonomy,
                        concept=concept,
                        unit=definition.unit,
                        start=_parse_date(item.get("start")),
                        end=end,
                        fiscal_year=item.get("fy") if isinstance(item.get("fy"), int) else None,
                        fiscal_period=item.get("fp"),
                        form=item["form"],
                        filed=filed,
                        accession_number=item["accn"],
                    )
                )
    return candidates


def _select(candidates: list[_Candidate]) -> dict[tuple[object, ...], _Candidate]:
    groups: dict[tuple[object, ...], list[_Candidate]] = defaultdict(list)
    for candidate in candidates:
        groups[(candidate.metric, *candidate.context)].append(candidate)
    selected: dict[tuple[object, ...], _Candidate] = {}
    for key, group in groups.items():
        deduplicated = {
            (
                item.accession_number,
                item.concept,
                item.start,
                item.end,
                item.value,
            ): item
            for item in group
        }
        latest_filed = max(item.filed for item in deduplicated.values())
        latest = [item for item in deduplicated.values() if item.filed == latest_filed]
        if len({item.value for item in latest}) > 1:
            continue
        selected[key] = min(latest, key=lambda item: item.alias_rank)
    return selected


def _to_fact(candidate: _Candidate) -> FinancialFact:
    return FinancialFact(
        value=candidate.value,
        taxonomy=candidate.taxonomy,
        concept=candidate.concept,
        unit=candidate.unit,
        start=candidate.start,
        end=candidate.end,
        fiscal_year=candidate.fiscal_year,
        fiscal_period=candidate.fiscal_period,
        form=candidate.form,
        filed=candidate.filed,
        accession_number=candidate.accession_number,
        reported=True,
        derived_from=[],
    )


def normalize_financials(
    payload: dict[str, Any],
    *,
    symbol: str,
    cik: str,
    period_type: Literal["annual", "quarterly"],
    count: int,
) -> FinancialStatement:
    selected = _select(_extract_candidates(payload, period_type))
    periods: dict[tuple[object, ...], dict[str, _Candidate]] = defaultdict(dict)
    for key, candidate in selected.items():
        period_key = (
            candidate.fiscal_year,
            candidate.fiscal_period,
            candidate.end,
        )
        current = periods[period_key].get(candidate.metric)
        if current is None or candidate.filed > current.filed:
            periods[period_key][candidate.metric] = candidate

    normalized: list[FinancialPeriod] = []
    for period_key, metrics in periods.items():
        fiscal_year, fiscal_period, period_end = period_key
        anchor = max(metrics.values(), key=lambda item: item.filed)
        normalized.append(
            FinancialPeriod(
                fiscal_year=fiscal_year,
                fiscal_period=fiscal_period,
                period_end=period_end,
                form=anchor.form,
                filed=anchor.filed,
                accession_number=anchor.accession_number,
                metrics={
                    name: _to_fact(metrics[name]) if name in metrics else None
                    for name in CONCEPTS
                },
            )
        )
    normalized.sort(key=lambda item: item.period_end, reverse=True)
    return FinancialStatement(
        symbol=symbol.upper(),
        cik=cik,
        period_type=period_type,
        periods=normalized[:count],
    )
```

- [ ] **Step 4: Run selection tests**

Run: `.venv/bin/pytest tests/test_sec_financials.py -q`

Expected: `3 passed`.

- [ ] **Step 5: Commit fact selection**

```bash
git add src/schwabber/sec_normalizer.py tests/fixtures/sec/company_facts.json tests/test_sec_financials.py
git commit -m "feat: select reported SEC financial facts"
```

### Task 6: Derive free cash flow only from aligned facts

**Files:**
- Modify: `src/schwabber/sec_normalizer.py`
- Modify: `tests/test_sec_financials.py`

- [ ] **Step 1: Write failing aligned and misaligned derivation tests**

```python
# Add to tests/test_sec_financials.py
def test_free_cash_flow_records_both_source_concepts() -> None:
    statement = normalize_financials(
        payload(), symbol="AMD", cik="0000002488", period_type="annual", count=5
    )
    free_cash_flow = statement.periods[0].metrics["free_cash_flow"]
    assert free_cash_flow is not None
    assert free_cash_flow.value == 150
    assert free_cash_flow.reported is False
    assert free_cash_flow.derived_from == [
        "NetCashProvidedByUsedInOperatingActivities",
        "PaymentsToAcquirePropertyPlantAndEquipment",
    ]


def test_free_cash_flow_is_null_when_accessions_do_not_align() -> None:
    body = deepcopy(payload())
    capex = body["facts"]["us-gaap"]["PaymentsToAcquirePropertyPlantAndEquipment"]
    capex["units"]["USD"][0]["accn"] = "0000002488-26-999999"
    statement = normalize_financials(
        body, symbol="AMD", cik="0000002488", period_type="annual", count=5
    )
    assert statement.periods[0].metrics["free_cash_flow"] is None
```

- [ ] **Step 2: Run derivation tests to verify they fail**

Run: `.venv/bin/pytest tests/test_sec_financials.py -k free_cash_flow -q`

Expected: FAIL because `free_cash_flow` is absent.

- [ ] **Step 3: Add the aligned derivation**

```python
# Add above normalize_financials in src/schwabber/sec_normalizer.py
def _derive_free_cash_flow(
    metrics: dict[str, FinancialFact | None],
) -> FinancialFact | None:
    operating = metrics.get("operating_cash_flow")
    capex = metrics.get("capital_expenditure")
    if operating is None or capex is None:
        return None
    alignment = (
        "unit",
        "start",
        "end",
        "fiscal_year",
        "fiscal_period",
        "form",
        "filed",
        "accession_number",
    )
    if any(getattr(operating, name) != getattr(capex, name) for name in alignment):
        return None
    return FinancialFact(
        value=operating.value - abs(capex.value),
        taxonomy="derived",
        concept="FreeCashFlow",
        unit=operating.unit,
        start=operating.start,
        end=operating.end,
        fiscal_year=operating.fiscal_year,
        fiscal_period=operating.fiscal_period,
        form=operating.form,
        filed=operating.filed,
        accession_number=operating.accession_number,
        reported=False,
        derived_from=[operating.concept, capex.concept],
    )
```

```python
# Replace the complete normalized.append(...) block in normalize_financials.
        period_metrics: dict[str, FinancialFact | None] = {
            name: _to_fact(metrics[name]) if name in metrics else None
            for name in CONCEPTS
        }
        period_metrics["free_cash_flow"] = _derive_free_cash_flow(period_metrics)
        normalized.append(
            FinancialPeriod(
                fiscal_year=fiscal_year,
                fiscal_period=fiscal_period,
                period_end=period_end,
                form=anchor.form,
                filed=anchor.filed,
                accession_number=anchor.accession_number,
                metrics=period_metrics,
            )
        )
```

- [ ] **Step 4: Run all financial tests**

Run: `.venv/bin/pytest tests/test_sec_financials.py -q`

Expected: `5 passed`.

- [ ] **Step 5: Commit derivation behavior**

```bash
git add src/schwabber/sec_normalizer.py tests/test_sec_financials.py
git commit -m "feat: derive aligned SEC free cash flow"
```

### Task 7: Add the cached SEC research service

**Files:**
- Create: `src/schwabber/services/sec.py`
- Create: `tests/test_sec_service.py`

- [ ] **Step 1: Write failing cache and bound tests**

```python
# tests/test_sec_service.py
import json
from pathlib import Path

import pytest

from schwabber.cache import TtlLruCache
from schwabber.errors import InvalidRequest
from schwabber.services.sec import SecResearchService


class Provider:
    ticker_calls = 0

    async def cik_for_symbol(self, symbol):
        self.ticker_calls += 1
        return "0000002488"

    async def submissions(self, cik):
        return json.loads(Path("tests/fixtures/sec/submissions.json").read_text())

    async def company_facts(self, cik):
        return json.loads(Path("tests/fixtures/sec/company_facts.json").read_text())


@pytest.mark.asyncio
async def test_financials_reuse_cached_symbol_lookup() -> None:
    provider = Provider()
    service = SecResearchService(provider, TtlLruCache())
    await service.financials("AMD", "annual", 5)
    second = await service.financials("AMD", "annual", 5)
    assert second.cache_hit is True
    assert provider.ticker_calls == 1


@pytest.mark.asyncio
async def test_filing_count_is_bounded() -> None:
    service = SecResearchService(Provider(), TtlLruCache())
    with pytest.raises(InvalidRequest, match="between 1 and 100"):
        await service.filings("AMD", ("10-K",), 101)
```

- [ ] **Step 2: Run service tests to verify they fail**

Run: `.venv/bin/pytest tests/test_sec_service.py -q`

Expected: FAIL because `SecResearchService` is absent.

- [ ] **Step 3: Implement SEC orchestration and TTLs**

```python
# src/schwabber/services/sec.py
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
        self,
        provider: SecProvider,
        cache: TtlLruCache[tuple[object, ...], object],
    ) -> None:
        self._provider = provider
        self._cache = cache

    async def _cik(self, symbol: str) -> str:
        key = ("sec_cik", symbol)
        cached = self._cache.get(key)
        if cached is not None:
            return cast(str, cached[0])
        cik = await self._provider.cik_for_symbol(symbol)
        self._cache.set(key, cik, 86_400)
        return cik

    async def financials(
        self,
        symbol: str,
        period_type: Literal["annual", "quarterly"],
        count: int,
    ) -> ServiceResult[FinancialStatement]:
        maximum = 20
        if not 1 <= count <= maximum:
            raise InvalidRequest("financial period count must be between 1 and 20")
        normalized_symbol = symbol.upper()
        key = ("sec_financials", normalized_symbol, period_type, count)
        cached = self._cache.get(key)
        if cached is not None:
            stored, age = cached
            result = cast(ServiceResult[FinancialStatement], stored)
            return ServiceResult(result.data, result.retrieved_at, True, age)
        cik = await self._cik(normalized_symbol)
        payload = await self._provider.company_facts(cik)
        statement = normalize_financials(
            payload,
            symbol=normalized_symbol,
            cik=cik,
            period_type=period_type,
            count=count,
        )
        result = ServiceResult(statement, datetime.now(UTC), False, 0)
        self._cache.set(key, result, 3_600)
        return result

    async def filings(
        self,
        symbol: str,
        forms: tuple[str, ...],
        count: int,
    ) -> ServiceResult[list[Filing]]:
        if not 1 <= count <= 100:
            raise InvalidRequest("filing count must be between 1 and 100")
        allowed = {"10-K", "10-Q", "8-K", "20-F", "6-K"}
        if not forms or not set(forms) <= allowed:
            raise InvalidRequest("forms contain an unsupported SEC form")
        normalized_symbol = symbol.upper()
        key = ("sec_filings", normalized_symbol, *forms, count)
        cached = self._cache.get(key)
        if cached is not None:
            stored, age = cached
            result = cast(ServiceResult[list[Filing]], stored)
            return ServiceResult(result.data, result.retrieved_at, True, age)
        cik = await self._cik(normalized_symbol)
        payload = await self._provider.submissions(cik)
        filings = normalize_filings(payload, cik=cik, forms=set(forms), limit=count)
        result = ServiceResult(filings, datetime.now(UTC), False, 0)
        self._cache.set(key, result, 300)
        return result
```

- [ ] **Step 4: Run SEC service tests**

Run: `.venv/bin/pytest tests/test_sec_service.py -q`

Expected: `2 passed`.

- [ ] **Step 5: Commit SEC services**

```bash
git add src/schwabber/services/sec.py tests/test_sec_service.py
git commit -m "feat: add cached SEC research service"
```

### Task 8: Expose financials and filings while preserving provider isolation

**Files:**
- Create: `src/schwabber/api/sec.py`
- Modify: `src/schwabber/api/dependencies.py`
- Modify: `src/schwabber/api/market.py`
- Modify: `src/schwabber/api/status.py`
- Modify: `src/schwabber/app.py`
- Create: `tests/test_sec_api.py`
- Modify: `tests/test_openapi.py`
- Modify: `tests/test_response_budget.py`

- [ ] **Step 1: Write failing API and outage-isolation tests**

```python
# tests/test_sec_api.py
import json
from pathlib import Path

from fastapi.testclient import TestClient

from schwabber.app import build_app
from schwabber.config import Settings
from schwabber.services.sec import SecResearchService
from schwabber.cache import TtlLruCache


class Provider:
    async def cik_for_symbol(self, symbol):
        return "0000002488"

    async def submissions(self, cik):
        return json.loads(Path("tests/fixtures/sec/submissions.json").read_text())

    async def company_facts(self, cik):
        return json.loads(Path("tests/fixtures/sec/company_facts.json").read_text())


def client() -> TestClient:
    settings = Settings.from_mapping(
        {
            "SCHWABBER_API_KEY": "k" * 32,
            "SEC_USER_AGENT": "Schwabber operator@example.com",
        }
    )
    service = SecResearchService(Provider(), TtlLruCache())
    return TestClient(build_app(settings, market_service=None, sec_service=service))


def test_financials_work_when_schwab_is_unavailable() -> None:
    response = client().get(
        "/v1/financials/AMD?period_type=annual&count=5",
        headers={"Authorization": f"Bearer {'k' * 32}"},
    )
    assert response.status_code == 200
    assert response.json()["meta"]["source"] == "sec"
    assert response.json()["data"]["periods"][0]["metrics"]["revenue"]["value"] == 1010


def test_recent_filings_return_official_links() -> None:
    response = client().get(
        "/v1/filings/AMD?forms=10-Q&count=20",
        headers={"Authorization": f"Bearer {'k' * 32}"},
    )
    assert response.status_code == 200
    assert response.json()["data"][0]["url"].startswith("https://www.sec.gov/")
```

```python
# Add to tests/test_openapi.py
def test_openapi_includes_sec_read_only_operations() -> None:
    schema = build_app(
        Settings.from_mapping({"SCHWABBER_API_KEY": "k" * 32})
    ).openapi()
    assert schema["paths"]["/v1/financials/{symbol}"]["get"]["operationId"] == "get_financials"
    assert schema["paths"]["/v1/filings/{symbol}"]["get"]["operationId"] == "get_recent_filings"
```

```python
# Add to tests/test_response_budget.py imports
from datetime import date

from schwabber.schemas.sec import Filing, FinancialFact, FinancialPeriod, FinancialStatement


# Add to tests/test_response_budget.py
def test_maximum_financial_shape_is_under_action_budget() -> None:
    fact = FinancialFact(
        value=9_999_999_999_999.99,
        taxonomy="us-gaap",
        concept="RevenueFromContractWithCustomerExcludingAssessedTax",
        unit="USD",
        start=date(2025, 1, 1),
        end=date(2025, 12, 31),
        fiscal_year=2025,
        fiscal_period="FY",
        form="10-K/A",
        filed=date(2026, 3, 1),
        accession_number="0000002488-26-000002",
        reported=True,
        derived_from=[],
    )
    metrics = {
        name: fact
        for name in (
            "revenue",
            "net_income",
            "diluted_eps",
            "assets",
            "liabilities",
            "stockholders_equity",
            "cash",
            "short_term_debt",
            "long_term_debt",
            "operating_cash_flow",
            "capital_expenditure",
            "free_cash_flow",
        )
    }
    statement = FinancialStatement(
        symbol="SYNTHETIC",
        cik="0000002488",
        period_type="annual",
        periods=[
            FinancialPeriod(
                fiscal_year=2025 - index,
                fiscal_period="FY",
                period_end=date(2025 - index, 12, 31),
                form="10-K/A",
                filed=date(2026 - index, 3, 1),
                accession_number=f"0000002488-{26 - index:02d}-000002",
                metrics=metrics,
            )
            for index in range(20)
        ],
    )
    body = SuccessEnvelope(data=statement, meta=meta(20)).model_dump_json(
        exclude_none=True
    )
    assert len(body) < 90_000


def test_maximum_filing_shape_is_under_action_budget() -> None:
    filings = [
        Filing(
            form="8-K",
            filing_date=date(2026, 8, 28),
            report_date=date(2026, 8, 27),
            accession_number=f"0000002488-26-{index:06d}",
            description="Synthetic current report description",
            primary_document=f"synthetic-{index}.htm",
            url=(
                "https://www.sec.gov/Archives/edgar/data/2488/"
                f"000000248826{index:06d}/synthetic-{index}.htm"
            ),
        )
        for index in range(100)
    ]
    body = SuccessEnvelope(data=filings, meta=meta(100)).model_dump_json(
        exclude_none=True
    )
    assert len(body) < 90_000
```

- [ ] **Step 2: Run route tests to verify they fail**

Run: `.venv/bin/pytest tests/test_sec_api.py tests/test_openapi.py -q`

Expected: FAIL because the SEC dependency and routes are absent.

- [ ] **Step 3: Add the dependency and routes**

```python
# Add to src/schwabber/api/dependencies.py
from schwabber.services.sec import SecResearchService


def sec_service(request: Request) -> SecResearchService:
    service = request.app.state.sec_service
    if service is None:
        raise ProviderUnavailable("SEC is not configured or available")
    return service
```

```python
# src/schwabber/api/sec.py
from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request

from schwabber.api.dependencies import sec_service
from schwabber.api.market import envelope
from schwabber.schemas.common import SuccessEnvelope
from schwabber.schemas.sec import Filing, FinancialStatement
from schwabber.services.sec import SecResearchService

router = APIRouter(prefix="/v1", tags=["SEC research"])


@router.get(
    "/financials/{symbol}",
    operation_id="get_financials",
    response_model=SuccessEnvelope[FinancialStatement],
    response_model_exclude_none=True,
)
async def get_financials(
    request: Request,
    symbol: str = Path(min_length=1, max_length=20),
    period_type: Literal["annual", "quarterly"] = "annual",
    count: int | None = Query(default=None, ge=1, le=20),
    service: SecResearchService = Depends(sec_service),
) -> SuccessEnvelope[FinancialStatement]:
    effective_count = count or (5 if period_type == "annual" else 8)
    result = await service.financials(symbol, period_type, effective_count)
    response = envelope(
        request,
        result,
        source="sec",
        filters={"period_type": period_type, "count": effective_count},
    )
    return response


@router.get(
    "/filings/{symbol}",
    operation_id="get_recent_filings",
    response_model=SuccessEnvelope[list[Filing]],
    response_model_exclude_none=True,
)
async def get_recent_filings(
    request: Request,
    symbol: str = Path(min_length=1, max_length=20),
    forms: str = Query(default="10-K,10-Q,8-K"),
    count: int = Query(default=20, ge=1, le=100),
    service: SecResearchService = Depends(sec_service),
) -> SuccessEnvelope[list[Filing]]:
    normalized_forms = tuple(
        dict.fromkeys(form.strip().upper() for form in forms.split(",") if form.strip())
    )
    result = await service.filings(symbol, normalized_forms, count)
    response = envelope(
        request,
        result,
        source="sec",
        filters={"forms": ",".join(normalized_forms), "count": count},
    )
    return response
```

```python
# Change the envelope signature and source assignment in src/schwabber/api/market.py
def envelope(
    request: Request,
    result: ServiceResult[T],
    *,
    source: Literal["schwab", "sec"] = "schwab",
    filters: dict[str, str | int | bool] | None = None,
) -> SuccessEnvelope[T]:
    return SuccessEnvelope(
        data=result.data,
        meta=ResponseMeta(
            source=source,
            retrieved_at=result.retrieved_at,
            request_id=request.state.request_id,
            cache=CacheMeta(
                hit=result.cache_hit,
                age_seconds=result.cache_age_seconds,
            ),
            result_count=len(result.data) if isinstance(result.data, list) else 1,
            truncated=result.truncated,
            filters=filters,
        ),
    )
```

```python
# In src/schwabber/app.py, add the import and parameter.
from schwabber.api.sec import router as sec_router
from schwabber.services.sec import SecResearchService


def build_app(
    settings: Settings,
    market_service: MarketService | None = None,
    sec_service: SecResearchService | None = None,
) -> FastAPI:
    # Keep the existing body and add these two assignments/registrations.
    app.state.sec_service = sec_service
    app.include_router(sec_router, dependencies=dependencies)
```

```python
# Update construction in src/schwabber/api/status.py
from schwabber.schemas.status import SchwabReadiness


        schwab=SchwabReadiness(
            configured=settings.schwab_configured,
            ready=request.app.state.market_service is not None,
            token=TokenStatusView(
                state=token.state,
                days_left=token.days_left,
                expires_at=token.expires_at,
            ),
        ),
        sec=ProviderReadiness(
            configured=settings.sec_configured,
            ready=request.app.state.sec_service is not None,
        ),
```

- [ ] **Step 4: Run route and OpenAPI tests**

Run: `.venv/bin/pytest tests/test_sec_api.py tests/test_openapi.py -q`

Expected: all tests PASS and both SEC operations use GET with bearer security.

- [ ] **Step 5: Commit the SEC API**

```bash
git add src/schwabber/api src/schwabber/app.py src/schwabber/schemas/status.py tests/test_sec_api.py tests/test_openapi.py tests/test_response_budget.py
git commit -m "feat: expose SEC financials and filings"
```

### Task 9: Wire the production SEC client and document its boundary

**Files:**
- Modify: `src/schwabber/app.py`
- Modify: `README.md`
- Modify: `tests/test_app.py`
- Modify: `tests/test_distribution.py`

- [ ] **Step 1: Write failing lifespan and documentation tests**

```python
# Add to tests/test_app.py
def test_sec_starts_when_schwab_is_unconfigured(monkeypatch) -> None:
    created = 0

    def factory(client, user_agent):
        nonlocal created
        created += 1
        return object()

    monkeypatch.setattr("schwabber.app.HttpSecProvider", factory)
    settings = Settings.from_mapping(
        {
            "SCHWABBER_API_KEY": "k" * 32,
            "SEC_USER_AGENT": "Schwabber operator@example.com",
        }
    )
    with TestClient(build_app(settings)):
        pass
    assert created == 1
```

```python
# Add to tests/test_distribution.py
def test_readme_documents_sec_identity_and_news_boundary() -> None:
    readme = Path("README.md").read_text()
    assert "SEC_USER_AGENT" in readme
    assert "web search" in readme.lower()
    assert "/v1/financials/{symbol}" in readme
    assert "/news" not in Path("src/schwabber/api/sec.py").read_text()
```

- [ ] **Step 2: Run focused tests to verify they fail**

Run: `.venv/bin/pytest tests/test_app.py tests/test_distribution.py -q`

Expected: FAIL because production lifespan creation and SEC documentation are absent.

- [ ] **Step 3: Create and close one SEC HTTP client in the lifespan**

```python
# Add these imports to src/schwabber/app.py
import httpx

from schwabber.providers.sec import HttpSecProvider


# Replace the lifespan function inside build_app with this definition.
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        sec_client: httpx.AsyncClient | None = None
        if app.state.market_service is None and settings.schwab_configured:
            try:
                provider = await create_schwab_provider(settings)
            except SchwabReauthRequired:
                app.state.market_service = None
            else:
                app.state.market_service = MarketService(
                    provider,
                    TtlLruCache(max_entries=1024),
                )
        if app.state.sec_service is None and settings.sec_configured:
            assert settings.sec_user_agent is not None
            sec_client = httpx.AsyncClient(
                timeout=httpx.Timeout(25.0, connect=3.0, read=10.0)
            )
            sec_provider = HttpSecProvider(sec_client, settings.sec_user_agent)
            app.state.sec_service = SecResearchService(
                sec_provider,
                TtlLruCache(max_entries=1024),
            )
        yield
        if sec_client is not None:
            await sec_client.aclose()
```

- [ ] **Step 4: Add exact SEC and news documentation**

````markdown
<!-- Append to README.md -->
## SEC EDGAR setup

Set `SEC_USER_AGENT` to an application and contact identity, for example:

```dotenv
SEC_USER_AGENT=Schwabber your-email@example.com
```

Restart the container after changing `.env`. The protected SEC operations are:

- `GET /v1/financials/{symbol}` for annual or directly reported quarterly facts.
- `GET /v1/filings/{symbol}` for bounded filing metadata and official SEC links.

Every financial value carries taxonomy, concept, unit, dates, form, filed date,
and accession provenance. Free cash flow is returned only when its operating
cash flow and capital expenditure inputs have the same filing context.

Schwabber has no `/news` route. Keep web search enabled in the private GPT for
headlines, reporting, estimates, and transcripts. Thinkorswim news is not
scraped or accessed through undocumented endpoints.
````

- [ ] **Step 5: Run the Phase 2 verification suite**

Run: `.venv/bin/pytest -q`

Expected: all tests PASS without network access or credentials.

Run: `.venv/bin/ruff check .`

Expected: `All checks passed!`

Run: `.venv/bin/mypy src`

Expected: `Success: no issues found`.

- [ ] **Step 6: Commit Phase 2 runtime and docs**

```bash
git add src/schwabber/app.py README.md tests/test_app.py tests/test_distribution.py
git commit -m "docs: add SEC setup and research boundary"
```

## Phase 2 completion gate

Run:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/mypy src
docker build -t schwabber:phase2 .
```

Expected:

- Every command exits zero and ordinary tests perform no network calls.
- Annual facts prefer the latest amendment for an identical context.
- Quarterly facts reject year-to-date durations and never synthesize Q4.
- Missing, conflicting, or incompatible concepts serialize as `null`.
- Free cash flow is derived only from aligned filing contexts.
- SEC routes remain usable when Schwab is unavailable, and the inverse remains true.
- Financial and filing maximum response tests remain below 90,000 characters.
