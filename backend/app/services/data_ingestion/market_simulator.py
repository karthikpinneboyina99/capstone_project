"""
MarketSimulator — deterministic OHLCV data for offline development and CI.

Two modes (selected automatically):
  1. DB Replay  — reads from price_bars when a SQLAlchemy session is provided and
                  rows exist for the requested ticker/range.
  2. Synthetic  — geometric Brownian motion (GBM) price series, seeded per-ticker
                  so the same ticker always produces the same path.

Design goals and guarantees: planning/MARKET_SIMULATOR.md
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from pandas.tseries.offsets import BDay

from .market_interface import Bar, Quote


# ---------------------------------------------------------------------------
# Per-ticker synthetic parameters
# ---------------------------------------------------------------------------

@dataclass
class _TickerParams:
    seed: int
    start_price: float
    mu: float     # daily drift
    sigma: float  # daily vol


_DEFAULTS = _TickerParams(seed=0, start_price=100.0, mu=0.0008, sigma=0.015)

_KNOWN: dict[str, _TickerParams] = {
    "AAPL":  _TickerParams(seed=1001, start_price=185.0, mu=0.0010, sigma=0.014),
    "MSFT":  _TickerParams(seed=1002, start_price=375.0, mu=0.0011, sigma=0.013),
    "NVDA":  _TickerParams(seed=1003, start_price=490.0, mu=0.0020, sigma=0.025),
    "GOOGL": _TickerParams(seed=1004, start_price=140.0, mu=0.0008, sigma=0.014),
    "AMZN":  _TickerParams(seed=1005, start_price=180.0, mu=0.0009, sigma=0.016),
    "META":  _TickerParams(seed=1006, start_price=480.0, mu=0.0012, sigma=0.018),
    "TSLA":  _TickerParams(seed=1007, start_price=250.0, mu=0.0005, sigma=0.030),
    "SPY":   _TickerParams(seed=2001, start_price=450.0, mu=0.0005, sigma=0.008),
    "QQQ":   _TickerParams(seed=2002, start_price=380.0, mu=0.0006, sigma=0.010),
    "BRK.B": _TickerParams(seed=2003, start_price=360.0, mu=0.0006, sigma=0.009),
}


def _params_for(ticker: str) -> _TickerParams:
    if ticker in _KNOWN:
        return _KNOWN[ticker]
    h = int(hashlib.sha256(ticker.encode()).hexdigest()[:8], 16)
    return _TickerParams(
        seed=h % (2 ** 31),
        start_price=50.0 + (h % 200),
        mu=_DEFAULTS.mu,
        sigma=_DEFAULTS.sigma,
    )


# ---------------------------------------------------------------------------
# Core simulator
# ---------------------------------------------------------------------------

class MarketSimulator:
    """
    Provides OHLCV data for any ticker over any date range.

    Priority:
      1. DB replay from price_bars (if db_session provided and rows exist)
      2. Synthetic GBM series (deterministic per ticker + seed)
    """

    _SIM_ORIGIN = date(2020, 1, 2)  # all synthetic series start here

    def __init__(self, db_session=None, seed: int = 42) -> None:
        self._db = db_session
        self._seed = seed

    # ------------------------------------------------------------------
    # Public API (mirrors MassiveProvider methods)
    # ------------------------------------------------------------------

    def get_bars(
        self,
        ticker: str,
        from_date: date,
        to_date: date,
        timespan: str = "day",
    ) -> pd.DataFrame:
        if self._db is not None:
            df = self._db_bars(ticker, from_date, to_date, timespan)
            if not df.empty:
                return df
        return self._synthetic_bars(ticker, from_date, to_date)

    def latest_bar(self, ticker: str) -> Bar:
        df = self.get_bars(ticker, date.today() - timedelta(days=7), date.today())
        if df.empty:
            p = _params_for(ticker).start_price
            return Bar(
                ticker=ticker,
                date=date.today(),
                open=p, high=p, low=p, close=p,
                volume=1_000_000,
                vwap=p,
            )
        row = df.iloc[-1]
        return Bar(
            ticker=ticker,
            date=row["date"].date(),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=int(row["volume"]),
            vwap=row.get("vwap"),
        )

    def latest_quote(self, ticker: str) -> Quote:
        bar = self.latest_bar(ticker)
        spread = bar.close * 0.0002  # synthetic 2bps spread
        return Quote(
            ticker=ticker,
            bid=round(bar.close - spread / 2, 4),
            ask=round(bar.close + spread / 2, 4),
            bid_size=100,
            ask_size=100,
            timestamp=pd.Timestamp.utcnow(),
        )

    def daily_summary(self, as_of: date) -> dict[str, Bar]:
        tickers = list(_KNOWN.keys())
        return {t: self.latest_bar(t) for t in tickers}

    # ------------------------------------------------------------------
    # DB replay
    # ------------------------------------------------------------------

    def _db_bars(
        self,
        ticker: str,
        from_date: date,
        to_date: date,
        timespan: str,
    ) -> pd.DataFrame:
        from sqlalchemy import text

        tf = "1d" if timespan == "day" else timespan
        rows = self._db.execute(
            text("""
                SELECT pb.timestamp, pb.open, pb.high, pb.low, pb.close, pb.volume
                FROM   price_bars pb
                JOIN   instruments i ON i.id = pb.instrument_id
                WHERE  i.symbol    = :ticker
                  AND  pb.timeframe = :tf
                  AND  pb.timestamp >= :from_ts
                  AND  pb.timestamp <= :to_ts
                ORDER BY pb.timestamp ASC
            """),
            {
                "ticker": ticker,
                "tf": tf,
                "from_ts": pd.Timestamp(from_date, tz="UTC"),
                "to_ts": pd.Timestamp(to_date, tz="UTC") + pd.Timedelta(days=1),
            },
        ).fetchall()

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(
            rows, columns=["date", "open", "high", "low", "close", "volume"]
        )
        df["date"] = (
            pd.to_datetime(df["date"], utc=True)
            .dt.tz_convert("America/New_York")
            .dt.normalize()
        )
        df["vwap"] = None
        return df[
            ["date", "open", "high", "low", "close", "volume", "vwap"]
        ].reset_index(drop=True)

    # ------------------------------------------------------------------
    # Synthetic GBM price series
    # ------------------------------------------------------------------

    def _synthetic_bars(
        self,
        ticker: str,
        from_date: date,
        to_date: date,
    ) -> pd.DataFrame:
        p = _params_for(ticker)
        rng = np.random.default_rng(p.seed ^ self._seed)

        bdays = pd.bdate_range(self._SIM_ORIGIN, to_date, freq="B")
        n = len(bdays)
        if n == 0:
            return pd.DataFrame(
                columns=["date", "open", "high", "low", "close", "volume", "vwap"]
            )

        # GBM path: S(t+1) = S(t) * exp((μ - σ²/2)*dt + σ*√dt*Z)
        dt = 1.0
        log_returns = (
            (p.mu - 0.5 * p.sigma ** 2) * dt
            + p.sigma * np.sqrt(dt) * rng.standard_normal(n)
        )
        closes = p.start_price * np.exp(np.cumsum(log_returns))

        intraday_sigma = p.sigma * 0.7
        daily_range = np.abs(rng.normal(0, intraday_sigma, n)) * closes

        opens = closes * np.exp(rng.normal(0, p.sigma * 0.3, n))
        highs = np.maximum(opens, closes) + daily_range * rng.uniform(0.2, 0.8, n)
        lows = np.minimum(opens, closes) - daily_range * rng.uniform(0.2, 0.8, n)
        lows = np.maximum(lows, 0.01)  # price floor
        volume = rng.lognormal(mean=np.log(5_000_000), sigma=0.5, size=n).astype(int)
        vwap = (opens + highs + lows + closes) / 4

        df = pd.DataFrame({
            "date": bdays,
            "open": np.round(opens, 4),
            "high": np.round(highs, 4),
            "low": np.round(lows, 4),
            "close": np.round(closes, 4),
            "volume": volume,
            "vwap": np.round(vwap, 4),
        })

        # Trim to requested range (no-lookahead guarantee).
        # Localize directly to ET midnight — bdate_range produces naive midnight
        # timestamps, so tz_localize gives the correct ET midnight boundary.
        # (Converting a date via UTC first shifts the boundary 5–4 hrs early.)
        from_ts = pd.Timestamp(str(from_date)).tz_localize("America/New_York")
        to_ts = pd.Timestamp(str(to_date)).tz_localize("America/New_York")
        df["date"] = df["date"].dt.tz_localize("America/New_York")
        df = df[(df["date"] >= from_ts) & (df["date"] <= to_ts)].reset_index(drop=True)
        return df
