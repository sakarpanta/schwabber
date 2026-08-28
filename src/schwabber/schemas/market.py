from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class Quote(BaseModel):
    symbol: str
    asset_type: str | None = None
    last_price: float | None = None
    bid_price: float | None = None
    ask_price: float | None = None
    mark: float | None = None
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    close_price: float | None = None
    total_volume: int | None = None
    quote_time: datetime | None = None
    trade_time: datetime | None = None
    is_realtime: bool | None = None


class Candle(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class Instrument(BaseModel):
    symbol: str
    description: str | None = None
    exchange: str | None = None
    asset_type: str | None = None
    market_cap: float | None = None
    pe_ratio: float | None = None
    eps: float | None = None
    dividend_yield: float | None = None
    beta: float | None = None
    shares_outstanding: float | None = None
    week_52_high: float | None = None
    week_52_low: float | None = None


class OptionContract(BaseModel):
    symbol: str
    underlying: str
    expiration: date
    strike: float
    put_call: Literal["PUT", "CALL"]
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    mark: float | None = None
    volume: int | None = None
    open_interest: int | None = None
    implied_volatility: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    rho: float | None = None
    quote_time: datetime | None = None
    is_realtime: bool | None = None


class Mover(BaseModel):
    symbol: str
    description: str | None = None
    last_price: float | None = None
    change: float | None = None
    percent_change: float | None = None
    volume: int | None = None


class MarketHours(BaseModel):
    market: str
    product: str | None = None
    date: date
    is_open: bool
    pre_market_start: datetime | None = None
    pre_market_end: datetime | None = None
    regular_start: datetime | None = None
    regular_end: datetime | None = None
    post_market_start: datetime | None = None
    post_market_end: datetime | None = None
