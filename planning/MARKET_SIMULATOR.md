# Market Simulator

The `SimulatorProvider` wraps a `MarketSimulator` that supplies price data when `MASSIVE_API_KEY` is absent. This covers three situations:

1. **CI / unit tests** — no API key available; all feature, ML, and backtest tests need reproducible price data.
2. **Offline development** — building the dashboard or backtester without burning API quota.
3. **Historical replay** — the backtester has already ingested bars into `price_bars`; the simulator can replay them without touching the network.

---

## Design Goals

| Goal | Constraint |
|------|-----------|
| Deterministic given a seed | Tests must be reproducible |
| DB-first | Replay real ingested data when available; synthetic only as a fallback |
| Correct shape | DataFrames must be identical in schema to `MassiveProvider` output |
| No lookahead | `get_bars(ticker, from, to)` returns only rows with `date <= to` |
| Realistic enough | Random-walk prices should preserve daily volatility characteristics and avoid negative prices |

---

## Two-Mode Architecture

```
get_bars(ticker, from_date, to_date)
        │
        ├─ price_bars table has rows for (ticker, from_date..to_date)?
        │        YES → DB Replay Mode
        │        NO  → Synthetic Mode
        │
        └─ Returns identical DataFrame schema either way
```

### Mode 1 — DB Replay

Reads directly from `price_bars` (SQLAlchemy `Session` injected at construction). This is the mode used by the backtester after historical ingestion runs.

```python
SELECT pb.timestamp, pb.open, pb.high, pb.low, pb.close, pb.volume
FROM   price_bars pb
JOIN   instruments i ON i.id = pb.instrument_id
WHERE  i.symbol   = :ticker
  AND  pb.timeframe = :timeframe        -- '1d' for daily
  AND  pb.timestamp >= :from_ts
  AND  pb.timestamp <= :to_ts
ORDER BY pb.timestamp ASC
```

All prices in `price_bars` are already adjusted (see plan.md section 8 — adjusted prices rule), so no further transformation is needed.

### Mode 2 — Synthetic Random Walk

Used when the DB has no data (CI, first-run tests). Generates a price series using geometric Brownian motion (GBM) — the standard model for equity prices:

```
S(t+1) = S(t) * exp( (μ - σ²/2) * dt + σ * √dt * Z )
where Z ~ N(0,1), dt = 1 day
```

Default parameters per-symbol are seeded from a deterministic hash of the ticker string so the same ticker always produces the same series, regardless of which symbols are requested together.

---

## Code Structure

```
backend/app/services/data_ingestion/
├── market_interface.py      # ABC + create_provider() factory
├── massive_provider.py      # Live Massive/Polygon REST implementation
├── simulator_provider.py    # Thin wrapper: MarketDataProvider → MarketSimulator
└── market_simulator.py      # Core simulator logic (this document)
```

---

## Full Implementation

```python
# backend/app/services/data_ingestion/market_simulator.py

from __future__ import annotations
import hashlib
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from pandas.tseries.offsets import BDay   # business-day offset

from .market_interface import Bar, Quote


# ---------------------------------------------------------------------------
# Per-ticker synthetic parameters — seeded so each ticker is consistent
# ---------------------------------------------------------------------------

@dataclass
class _TickerParams:
    seed:      int
    start_price: float   # synthetic "IPO" price
    mu:        float     # daily drift (annualised / 252)
    sigma:     float     # daily volatility (annualised / sqrt(252))


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
    # Deterministic fallback: hash ticker name → reproducible seed + price
    h = int(hashlib.sha256(ticker.encode()).hexdigest()[:8], 16)
    return _TickerParams(
        seed=h % (2**31),
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

    _SIM_ORIGIN = date(2020, 1, 2)   # all synthetic series start here

    def __init__(self, db_session=None, seed: int = 42) -> None:
        self._db  = db_session
        self._seed = seed

    # -----------------------------------------------------------------------
    # Public API (mirrors MassiveProvider methods)
    # -----------------------------------------------------------------------

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
            return Bar(ticker=ticker, date=date.today(), open=p, high=p, low=p, close=p,
                       volume=1_000_000, vwap=p)
        row = df.iloc[-1]
        return Bar(
            ticker=ticker, date=row["date"].date(),
            open=row["open"], high=row["high"], low=row["low"], close=row["close"],
            volume=int(row["volume"]), vwap=row.get("vwap"),
        )

    def latest_quote(self, ticker: str) -> Quote:
        bar = self.latest_bar(ticker)
        spread = bar.close * 0.0002   # synthetic 2bps spread
        return Quote(
            ticker=ticker,
            bid=round(bar.close - spread / 2, 4),
            ask=round(bar.close + spread / 2, 4),
            bid_size=100, ask_size=100,
            timestamp=pd.Timestamp.utcnow(),
        )

    def daily_summary(self, as_of: date) -> dict[str, Bar]:
        tickers = list(_KNOWN.keys())
        return {t: self.latest_bar(t) for t in tickers}

    # -----------------------------------------------------------------------
    # DB replay
    # -----------------------------------------------------------------------

    def _db_bars(self, ticker: str, from_date: date, to_date: date, timespan: str) -> pd.DataFrame:
        from sqlalchemy import text
        tf = "1d" if timespan == "day" else timespan
        rows = self._db.execute(text("""
            SELECT pb.timestamp, pb.open, pb.high, pb.low, pb.close, pb.volume
            FROM   price_bars pb
            JOIN   instruments i ON i.id = pb.instrument_id
            WHERE  i.symbol    = :ticker
              AND  pb.timeframe = :tf
              AND  pb.timestamp >= :from_ts
              AND  pb.timestamp <= :to_ts
            ORDER BY pb.timestamp ASC
        """), {"ticker": ticker, "tf": tf,
               "from_ts": pd.Timestamp(from_date, tz="UTC"),
               "to_ts":   pd.Timestamp(to_date,   tz="UTC") + pd.Timedelta(days=1)}).fetchall()

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
        df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_convert("America/New_York").dt.normalize()
        df["vwap"] = None
        return df[["date", "open", "high", "low", "close", "volume", "vwap"]].reset_index(drop=True)

    # -----------------------------------------------------------------------
    # Synthetic GBM price series
    # -----------------------------------------------------------------------

    def _synthetic_bars(self, ticker: str, from_date: date, to_date: date) -> pd.DataFrame:
        p = _params_for(ticker)
        rng = np.random.default_rng(p.seed ^ self._seed)

        # Generate daily closes from simulation origin to to_date (inclusive)
        bdays = pd.bdate_range(self._SIM_ORIGIN, to_date, freq="B")
        n = len(bdays)
        if n == 0:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "vwap"])

        # GBM path
        dt = 1.0
        log_returns = (p.mu - 0.5 * p.sigma ** 2) * dt + p.sigma * np.sqrt(dt) * rng.standard_normal(n)
        closes = p.start_price * np.exp(np.cumsum(log_returns))

        # Intraday range from close
        intraday_sigma = p.sigma * 0.7   # intraday vol is ~70% of close-to-close vol
        daily_range = np.abs(rng.normal(0, intraday_sigma, n)) * closes

        opens  = closes * np.exp(rng.normal(0, p.sigma * 0.3, n))
        highs  = np.maximum(opens, closes) + daily_range * rng.uniform(0.2, 0.8, n)
        lows   = np.minimum(opens, closes) - daily_range * rng.uniform(0.2, 0.8, n)
        lows   = np.maximum(lows, 0.01)    # price floor
        volume = (rng.lognormal(mean=np.log(5_000_000), sigma=0.5, size=n)).astype(int)
        vwap   = (opens + highs + lows + closes) / 4   # typical price approximation

        df = pd.DataFrame({
            "date":   bdays,
            "open":   np.round(opens,  4),
            "high":   np.round(highs,  4),
            "low":    np.round(lows,   4),
            "close":  np.round(closes, 4),
            "volume": volume,
            "vwap":   np.round(vwap,   4),
        })

        # Trim to requested range
        from_ts = pd.Timestamp(from_date, tz="UTC").tz_convert("America/New_York")
        to_ts   = pd.Timestamp(to_date,   tz="UTC").tz_convert("America/New_York")
        df["date"] = df["date"].dt.tz_localize("America/New_York")
        df = df[(df["date"] >= from_ts) & (df["date"] <= to_ts)].reset_index(drop=True)
        return df
```

---

## Guarantees the Simulator Provides

| Property | Guarantee |
|----------|-----------|
| Schema | Identical column set to `MassiveProvider`: `date, open, high, low, close, volume, vwap` |
| Adjusted prices | Synthetic — there are no splits to adjust for; DB replay uses already-adjusted `price_bars` |
| No lookahead | `get_bars(ticker, from, to)` never returns rows with `date > to` |
| Determinism | Same ticker + same seed → same GBM path across test runs |
| Positive prices | Hard floor at $0.01; exponential GBM cannot go negative |
| High ≥ open, close | Enforced by construction |
| Low ≤ open, close | Enforced by construction; floored at $0.01 |

---

## What the Simulator Does NOT Provide

- **Corporate events** (splits, dividends, mergers) — no price discontinuities.
- **Realistic correlations between tickers** — each ticker's path is independent.
- **Earnings gaps or news-driven moves** — returns are drawn from a stationary distribution.
- **Intraday sub-minute data** — only daily bars are well-modelled; minute-bar generation is a stretch goal.
- **Pre/after-hours data** — `open` and `close` are within-session prices only.

These limitations are acceptable because the simulator's purpose is testing correctness (schema shape, no-lookahead, feature computation), not validating the strategy's alpha.

---

## Testing the Simulator

```python
# tests/backend/test_market_simulator.py
import pytest
from datetime import date
from app.services.data_ingestion.market_simulator import MarketSimulator

SIM = MarketSimulator(db_session=None, seed=42)

def test_schema():
    df = SIM.get_bars("AAPL", date(2023, 1, 1), date(2023, 3, 31))
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume", "vwap"]
    assert len(df) > 0

def test_no_lookahead():
    to = date(2023, 6, 15)
    df = SIM.get_bars("AAPL", date(2023, 1, 1), to)
    assert df["date"].dt.date.max() <= to

def test_ohlc_invariants():
    df = SIM.get_bars("MSFT", date(2022, 1, 1), date(2022, 12, 31))
    assert (df["high"] >= df["open"]).all()
    assert (df["high"] >= df["close"]).all()
    assert (df["low"]  <= df["open"]).all()
    assert (df["low"]  <= df["close"]).all()
    assert (df["close"] > 0).all()

def test_deterministic():
    df1 = SIM.get_bars("NVDA", date(2023, 1, 1), date(2023, 6, 30))
    df2 = MarketSimulator(seed=42).get_bars("NVDA", date(2023, 1, 1), date(2023, 6, 30))
    pd.testing.assert_frame_equal(df1, df2)

def test_unknown_ticker():
    df = SIM.get_bars("XYZFAKE", date(2023, 1, 1), date(2023, 3, 31))
    assert len(df) > 0   # falls back to hash-seeded defaults
```
