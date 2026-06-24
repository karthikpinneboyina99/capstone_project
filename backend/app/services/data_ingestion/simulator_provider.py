"""
SimulatorProvider — MarketDataProvider backed by MarketSimulator.

Used when MASSIVE_API_KEY is absent (CI, unit tests, offline development).
Attempts DB replay first; falls back to GBM synthetic data when no price_bars
rows exist for the requested range.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from .market_interface import Bar, MarketDataProvider, Quote
from .market_simulator import MarketSimulator


class SimulatorProvider(MarketDataProvider):
    """Wraps MarketSimulator, implementing the full MarketDataProvider interface."""

    def __init__(self, db_session=None, seed: int = 42) -> None:
        self._sim = MarketSimulator(db_session=db_session, seed=seed)

    def get_bars(
        self,
        tickers: list[str],
        from_date: date,
        to_date: date,
        timespan: str = "day",
    ) -> dict[str, pd.DataFrame]:
        return {t: self._sim.get_bars(t, from_date, to_date, timespan) for t in tickers}

    def get_latest_quote(self, tickers: list[str]) -> dict[str, Quote]:
        return {t: self._sim.latest_quote(t) for t in tickers}

    def get_snapshot(self, tickers: list[str]) -> dict[str, Bar]:
        return {t: self._sim.latest_bar(t) for t in tickers}

    def get_daily_market_summary(self, as_of: date) -> dict[str, Bar]:
        return self._sim.daily_summary(as_of)
