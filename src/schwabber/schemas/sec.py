from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class Filing(BaseModel):
    form: str
    filing_date: date
    report_date: date | None = None
    accession_number: str
    description: str | None = None
    primary_document: str
    url: str = Field(description="Direct SEC URL for the filing's primary document.")


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
    reported: bool = Field(
        description="True when the value comes directly from a selected SEC fact."
    )
    derived_from: list[str] = Field(
        description="Metric names used to calculate the value; empty when reported."
    )


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
