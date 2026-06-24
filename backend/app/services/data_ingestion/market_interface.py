"""
Unified market data interface.

Active provider is selected at import time via create_provider():
  - MASSIVE_API_KEY is set  → MassiveProvider (live Polygon/Massive REST API)
  - MASSIVE_API_KEY absent  → SimulatorProvider (DB replay + GBM synthetic fallback)

All callers (feature engineering, backtester, live executor) import from here and
never call the Massive API directly.
"""
from __future__ import annotations

import abc
import os
from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass(frozen=True)
class Bar:
    """One OHLCV bar. Prices are always split-and-dividend adjusted."""

    ticker: str
    date: date          # trading date (ET)
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: float | None  # None if not available (simulator may omit)


@dataclass(frozen=True)
class Quote:
    """Best bid/ask at a point in time. Only available from MassiveProvider (Advanced plan)."""

    ticker: str
    bid: float
    ask: float
    bid_size: int
    ask_size: int
    timestamp: pd.Timestamp  # tz-aware UTC


class MarketDataProvider(abc.ABC):
    """Abstract base — never instantiate directly; use create_provider()."""

    @abc.abstractmethod
    def get_bars(
        self,
        tickers: list[str],
        from_date: date,
        to_date: date,
        timespan: str = "day",
    ) -> dict[str, pd.DataFrame]:
        """
        Return OHLCV DataFrames keyed by ticker.

        DataFrame columns: date (DatetimeTZDtype, America/New_York), open, high,
        low, close, volume, vwap. Index is a default RangeIndex; rows sorted
        ascending by date. All prices adjusted.
        """

    @abc.abstractmethod
    def get_latest_quote(self, tickers: list[str]) -> dict[str, Quote]:
        """
        Return the most recent best bid/ask per ticker.
        SimulatorProvider returns a synthetic quote derived from the last close.
        """

    @abc.abstractmethod
    def get_snapshot(self, tickers: list[str]) -> dict[str, Bar]:
        """
        Return the most recent EOD (or intraday if available) bar per ticker.
        Used by the live executor to price open positions.
        """

    @abc.abstractmethod
    def get_daily_market_summary(self, as_of: date) -> dict[str, Bar]:
        """
        Return EOD bars for every ticker on a given date.
        Primarily used during bulk historical ingestion.
        MassiveProvider calls /v2/aggs/grouped; SimulatorProvider reads price_bars.
        """


def create_provider(db_session=None) -> MarketDataProvider:
    """
    Returns the live MassiveProvider when MASSIVE_API_KEY is in the environment,
    otherwise returns SimulatorProvider. Callers never need to know which.
    """
    key = os.environ.get("MASSIVE_API_KEY")
    if key:
        from .massive_provider import MassiveProvider
        return MassiveProvider(api_key=key)
    from .simulator_provider import SimulatorProvider
    return SimulatorProvider(db_session=db_session)
