from collections import defaultdict
from datetime import date
from typing import Any, Literal

from schwabber.errors import UpstreamFailure
from schwabber.schemas.sec import (
    Filing,
    FinancialFact,
    FinancialPeriod,
    FinancialStatement,
)
from schwabber.sec_concepts import CONCEPTS, ConceptDefinition


def _parse(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def normalize_filings(
    payload: dict[str, Any], *, cik: str, forms: set[str], limit: int
) -> list[Filing]:
    recent = payload.get("filings", {}).get("recent", {})
    names = (
        "accessionNumber",
        "filingDate",
        "reportDate",
        "form",
        "primaryDocument",
        "primaryDocDescription",
    )
    columns = [recent.get(name) for name in names]
    if (
        not all(isinstance(column, list) for column in columns)
        or len({len(c) for c in columns}) != 1
    ):
        raise UpstreamFailure("SEC submissions response is missing recent filings")
    result = []
    for accession, filing, report, form, document, description in zip(
        *columns, strict=True
    ):
        if form not in forms:
            continue
        result.append(
            Filing(
                form=form,
                filing_date=date.fromisoformat(filing),
                report_date=_parse(report),
                accession_number=accession,
                description=description or None,
                primary_document=document,
                url=(
                    "https://www.sec.gov/Archives/edgar/data/"
                    f"{int(cik)}/{accession.replace('-', '')}/{document}"
                ),
            )
        )
        if len(result) >= limit:
            break
    return result


def _duration_ok(
    item: dict[str, Any], definition: ConceptDefinition, period_type: str
) -> bool:
    if not definition.duration:
        return True
    start, end = _parse(item.get("start")), _parse(item.get("end"))
    if start is None or end is None:
        return False
    days = (end - start).days + 1
    return 300 <= days <= 430 if period_type == "annual" else 70 <= days <= 120


def normalize_financials(
    payload: dict[str, Any],
    *,
    symbol: str,
    cik: str,
    period_type: Literal["annual", "quarterly"],
    count: int,
) -> FinancialStatement:
    groups: dict[tuple[Any, ...], dict[str, FinancialFact]] = defaultdict(dict)
    for metric, definition in CONCEPTS.items():
        for taxonomy, concept in definition.aliases:
            records = (
                payload.get("facts", {})
                .get(taxonomy, {})
                .get(concept, {})
                .get("units", {})
                .get(definition.unit, [])
            )
            for item in records if isinstance(records, list) else []:
                form, fp = item.get("form"), item.get("fp")
                allowed = (
                    {"10-K", "10-K/A", "20-F", "20-F/A"}
                    if period_type == "annual"
                    else {"10-Q", "10-Q/A", "6-K", "6-K/A"}
                )
                if (
                    form not in allowed
                    or (
                        fp != "FY"
                        if period_type == "annual"
                        else fp not in {"Q1", "Q2", "Q3"}
                    )
                    or not _duration_ok(item, definition, period_type)
                ):
                    continue
                end, filed = _parse(item.get("end")), _parse(item.get("filed"))
                if (
                    end is None
                    or filed is None
                    or not isinstance(item.get("val"), (int, float))
                ):
                    continue
                key = (fp, end)
                fact = FinancialFact(
                    value=float(item["val"]),
                    taxonomy=taxonomy,
                    concept=concept,
                    unit=definition.unit,
                    start=_parse(item.get("start")),
                    end=end,
                    fiscal_year=item.get("fy"),
                    fiscal_period=fp,
                    form=form,
                    filed=filed,
                    accession_number=item.get("accn", ""),
                    reported=True,
                    derived_from=[],
                )
                old = groups[key].get(metric)
                matches_period_year = (
                    period_type == "annual" and item.get("fy") == end.year
                )
                old_matches_period_year = (
                    old is not None and old.fiscal_year == end.year
                )
                if (
                    old is None
                    or (matches_period_year and not old_matches_period_year)
                    or (
                        matches_period_year == old_matches_period_year
                        and filed > old.filed
                    )
                ):
                    groups[key][metric] = fact
    periods = []
    for (fp, end), metrics in groups.items():
        anchor = max(metrics.values(), key=lambda f: f.filed)
        periods.append(
            FinancialPeriod(
                fiscal_year=anchor.fiscal_year,
                fiscal_period=fp,
                period_end=end,
                form=anchor.form,
                filed=anchor.filed,
                accession_number=anchor.accession_number,
                metrics={name: metrics.get(name) for name in CONCEPTS},
            )
        )
    periods.sort(key=lambda p: p.period_end, reverse=True)
    return FinancialStatement(
        symbol=symbol.upper(), cik=cik, period_type=period_type, periods=periods[:count]
    )
