# Market Data Backend — Implementation Design

This document is the authoritative implementation guide for the market data layer.
It synthesises `MARKET_INTERFACE.md`, `MASSIVE_API.md`, and `MARKET_SIMULATOR.md`
into concrete, copy-ready code covering every module, edge case, wiring decision,
and test. Read this before touching any file under
`backend/app/services/data_ingestion/`.

---

## Table of Contents

1. [System Map](#1-system-map)
2. [File Layout](#2-file-layout)
3. [Unified API — `market_interface.py`](#3-unified-api--market_interfacepy)
4. [Massive/Polygon Provider — `massive_provider.py`](#4-massivepolygon-provider--massive_providerpy)
5. [Market Simulator — `market_simulator.py`](#5-market-simulator--market_simulatorpy)
6. [Simulator Provider — `simulator_provider.py`](#6-simulator-provider--simulator_providerpy)
7. [Historical Ingestion Loader — `yfinance_loader.py`](#7-historical-ingestion-loader--yfinance_loaderpy)
8. [News Loader — `news_loader.py`](#8-news-loader--news_loaderpy)
9. [Live/Daily Ingestion — `alpaca_loader.py`](#9-livedaily-ingestion--alpaca_loaderpy)
10. [Database Upsert Helpers — `db_writer.py`](#10-database-upsert-helpers--db_writerpy)
11. [Rate-Limit & Retry Utilities — `retry.py`](#11-rate-limit--retry-utilities--retrypy)
12. [FastAPI Wiring — ingestion endpoints](#12-fastapi-wiring--ingestion-endpoints)
13. [Environment Variables](#13-environment-variables)
14. [Testing Strategy & Test Fixtures](#14-testing-strategy--test-fixtures)
15. [Operational Runbook](#15-operational-runbook)
16. [Design Decisions Reference](#16-design-decisions-reference)

---

## 1. System Map

```
External sources                 Internal callers
─────────────────                ──────────────────────────────────────────
Massive/Polygon REST API ───┐    Feature Engineering
yfinance (backfill only) ───┼──► create_provider()  ──► MarketDataProvider (ABC)
NewsAPI headlines        ───┘         │                        │
                                      │            ┌───────────┴──────────────┐
                                      │            ▼                          ▼
                             MASSIVE_API_KEY set?  MassiveProvider    SimulatorProvider
                                                        │                     │
                                                        ▼                     ▼
                                               Polygon REST API        MarketSimulator
                                                                       (DB replay │ GBM)
                                                                              │
                                                                       price_bars table
```

**Single rule for all callers:** import `create_provider` and call it. Never
import `MassiveProvider` or `SimulatorProvider` directly in business logic.

---

## 2. File Layout

```
backend/app/services/data_ingestion/
├── __init__.py
├── market_interface.py      # ABC + Bar/Quote dataclasses + create_provider()
├── massive_provider.py      # Polygon/Massive REST implementation
├── simulator_provider.py    # Thin wrapper → MarketSimulator
├── market_simulator.py      # DB-replay + GBM fallback
├── yfinance_loader.py       # Historical bulk ingest (2–5 year backfill)
├── alpaca_loader.py         # Live/daily ingest via alpaca-py
├── news_loader.py           # Headlines via NewsAPI
├── db_writer.py             # Shared upsert helpers for price_bars, news_articles
└── retry.py                 # Tenacity-based retry decorators
```

---

## 3. Unified API — `market_interface.py`

This module owns the only public interface that every downstream consumer uses.

```python
# backend/app/services/data_ingestion/market_interface.py

from __future__ import annotations

import abc
import os
from dataclasses import dataclass
from datetime import date

import pandas as pd


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Bar:
    """One OHLCV bar. Prices are always split-and-dividend adjusted."""
    ticker:  str
    date:    date           # trading date in America/New_York
    open:    float
    high:    float
    low:     float
    close:   float
    volume:  int
    vwap:    float | None   # None when not available (simulator may omit)


@dataclass(frozen=True)
class Quote:
    """Best bid/ask snapshot. MassiveProvider (Advanced plan) returns real quotes;
    SimulatorProvider synthesises a 2 bps spread around the last close."""
    ticker:    str
    bid:       float
    ask:       float
    bid_size:  int
    ask_size:  int
    timestamp: pd.Timestamp   # always tz-aware UTC


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class MarketDataProvider(abc.ABC):
    """
    Abstract interface. All callers receive one of these; they never know
    whether they are talking to the live API or the simulator.
    """

    @abc.abstractmethod
    def get_bars(
        self,
        tickers: list[str],
        from_date: date,
        to_date: date,
        timespan: str = "day",
    ) -> dict[str, pd.DataFrame]:
        """
        Return a dict of DataFrames keyed by ticker symbol.

        Column contract (identical for both providers):
            date    — DatetimeTZDtype(America/New_York), one row per trading day
            open    — float, adjusted
            high    — float, adjusted
            low     — float, adjusted
            close   — float, adjusted
            volume  — int
            vwap    — float or NaN

        Rows are sorted ascending by date. Index is a default RangeIndex.
        Rows with date > to_date are NEVER returned (no-lookahead guarantee).
        """

    @abc.abstractmethod
    def get_latest_quote(self, tickers: list[str]) -> dict[str, Quote]:
        """Most recent best bid/ask per ticker."""

    @abc.abstractmethod
    def get_snapshot(self, tickers: list[str]) -> dict[str, Bar]:
        """Most recent EOD (or intraday) bar per ticker.
        Used by the live executor to price open positions."""

    @abc.abstractmethod
    def get_daily_market_summary(self, as_of: date) -> dict[str, Bar]:
        """EOD bars for every ticker on a given calendar date.
        MassiveProvider calls /v2/aggs/grouped; SimulatorProvider reads price_bars."""


# ---------------------------------------------------------------------------
# Factory — the only import most callers need
# ---------------------------------------------------------------------------

def create_provider(db_session=None) -> MarketDataProvider:
    """
    Returns MassiveProvider when MASSIVE_API_KEY is set in the environment,
    otherwise SimulatorProvider. The db_session is passed through to the
    simulator so it can replay real ingested data from price_bars.

    Usage:
        provider = create_provider(db_session=db)
        bars = provider.get_bars(["AAPL", "SPY"], date(2022,1,1), date(2023,12,31))
    """
    key = os.environ.get("MASSIVE_API_KEY")
    if key:
        from .massive_provider import MassiveProvider
        return MassiveProvider(api_key=key)
    from .simulator_provider import SimulatorProvider
    return SimulatorProvider(db_session=db_session)
```

### Why an ABC and not duck-typing?

Mypy catches missing method implementations at import time. Both providers are
concrete subtypes so the type checker can verify call sites without having to
run the code.

---

## 4. Massive/Polygon Provider — `massive_provider.py`

Polygon.io rebranded to **Massive** in 2025. The REST API surface is unchanged;
only the canonical hostname changed to `api.massive.com`. The legacy
`api.polygon.io` hostname still works (HTTP 301 redirect) — we keep it as
default so existing keys continue to work without changes.

### Key API facts

| Endpoint | Used for |
|----------|---------|
| `GET /v2/aggs/ticker/{t}/range/1/day/{from}/{to}` | Historical daily bars (primary) |
| `GET /v2/aggs/grouped/locale/global/market/stocks/{date}` | Bulk EOD for all tickers |
| `GET /v2/aggs/ticker/{t}/prev` | Previous trading day bar |
| `GET /v2/snapshot/locale/us/markets/stocks/tickers` | Multi-ticker snapshot |
| `GET /v2/snapshot/locale/us/markets/stocks/{direction}` | Top gainers/losers |

All REST timestamps are **Unix milliseconds UTC**.

```python
# backend/app/services/data_ingestion/massive_provider.py

from __future__ import annotations

import os
import time
from datetime import date

import pandas as pd
import requests

from .market_interface import Bar, MarketDataProvider, Quote
from .retry import with_backoff   # see section 11


_BASE = os.environ.get("MASSIVE_BASE_URL", "https://api.polygon.io")
_TIMESPAN_MAP = {"day": "day", "minute": "minute", "hour": "hour", "week": "week"}


class MassiveProvider(MarketDataProvider):
    """
    Calls the Massive (Polygon.io) REST API for live and historical data.
    Requires MASSIVE_API_KEY in the environment.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._key = api_key or os.environ["MASSIVE_API_KEY"]

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_bars(
        self,
        tickers: list[str],
        from_date: date,
        to_date: date,
        timespan: str = "day",
    ) -> dict[str, pd.DataFrame]:
        """
        Fetch OHLCV bars for multiple tickers.

        Makes one HTTP request per ticker. For large watchlists (>20 symbols)
        consider calling concurrently with asyncio + httpx, but for the Starter
        plan's ~5 req/min limit sequential is safer.
        """
        results: dict[str, pd.DataFrame] = {}
        for ticker in tickers:
            raw = self._fetch_aggs(ticker, from_date, to_date, timespan)
            results[ticker] = self._to_df(raw)
        return results

    def get_latest_quote(self, tickers: list[str]) -> dict[str, Quote]:
        snaps = self._get_snapshots(tickers)
        out: dict[str, Quote] = {}
        for ticker, snap in snaps.items():
            lt = snap.get("lastQuote") or {}
            # Starter plan does not provide real-time quotes; fall back to last trade
            last_trade = snap.get("lastTrade") or {}
            price = last_trade.get("p") or snap.get("day", {}).get("c", 0.0)
            out[ticker] = Quote(
                ticker=ticker,
                bid=lt.get("P", price),
                ask=lt.get("P", price),
                bid_size=lt.get("S", 0),
                ask_size=lt.get("S", 0),
                timestamp=pd.Timestamp(snap.get("updated", 0), unit="ns", tz="UTC"),
            )
        return out

    def get_snapshot(self, tickers: list[str]) -> dict[str, Bar]:
        snaps = self._get_snapshots(tickers)
        out: dict[str, Bar] = {}
        for ticker, snap in snaps.items():
            # Prefer intraday "day" bucket; fall back to "prevDay"
            day = snap.get("day") or snap.get("prevDay") or {}
            out[ticker] = Bar(
                ticker=ticker,
                date=date.today(),
                open=day.get("o", 0.0),
                high=day.get("h", 0.0),
                low=day.get("l", 0.0),
                close=day.get("c", 0.0),
                volume=int(day.get("v", 0)),
                vwap=day.get("vw"),
            )
        return out

    def get_daily_market_summary(self, as_of: date) -> dict[str, Bar]:
        """Returns EOD bars for ALL US equities on a single date — one API call."""
        url = f"{_BASE}/v2/aggs/grouped/locale/global/market/stocks/{as_of}"
        body = self._get(url, {"adjusted": "true"})
        out: dict[str, Bar] = {}
        for item in body.get("results") or []:
            t = item.get("T", "")
            if not t:
                continue
            out[t] = Bar(
                ticker=t,
                date=as_of,
                open=item["o"],
                high=item["h"],
                low=item["l"],
                close=item["c"],
                volume=int(item["v"]),
                vwap=item.get("vw"),
            )
        return out

    # ------------------------------------------------------------------
    # Convenience helpers (not on the ABC; call via isinstance check if needed)
    # ------------------------------------------------------------------

    def get_prev_day(self, ticker: str) -> Bar | None:
        """Single-ticker previous trading day bar."""
        url = f"{_BASE}/v2/aggs/ticker/{ticker}/prev"
        body = self._get(url, {"adjusted": "true"})
        results = body.get("results") or []
        if not results:
            return None
        r = results[0]
        bar_date = pd.Timestamp(r["t"], unit="ms", utc=True).tz_convert("America/New_York").date()
        return Bar(
            ticker=ticker,
            date=bar_date,
            open=r["o"], high=r["h"], low=r["l"], close=r["c"],
            volume=int(r["v"]), vwap=r.get("vw"),
        )

    def get_top_movers(self, direction: str = "gainers") -> list[Bar]:
        """Top 20 gainers or losers by percentage change (snapshot)."""
        assert direction in ("gainers", "losers"), "direction must be 'gainers' or 'losers'"
        url = f"{_BASE}/v2/snapshot/locale/us/markets/stocks/{direction}"
        body = self._get(url, {})
        out = []
        for snap in body.get("tickers") or []:
            ticker = snap["ticker"]
            day = snap.get("day") or {}
            out.append(Bar(
                ticker=ticker,
                date=date.today(),
                open=day.get("o", 0.0), high=day.get("h", 0.0),
                low=day.get("l", 0.0),  close=day.get("c", 0.0),
                volume=int(day.get("v", 0)), vwap=day.get("vw"),
            ))
        return out

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_aggs(
        self,
        ticker: str,
        from_date: date,
        to_date: date,
        timespan: str,
    ) -> list[dict]:
        """Fetch all aggregate bars, following pagination cursors until exhausted."""
        ts = _TIMESPAN_MAP.get(timespan, "day")
        url = f"{_BASE}/v2/aggs/ticker/{ticker}/range/1/{ts}/{from_date}/{to_date}"
        params: dict = {"adjusted": "true", "sort": "asc", "limit": 50000}
        results: list[dict] = []
        while url:
            body = self._get(url, params)
            results.extend(body.get("results") or [])
            url = body.get("next_url")   # None when last page
            params = {}                  # next_url is self-contained; only re-add apiKey
        return results

    def _get_snapshots(self, tickers: list[str]) -> dict[str, dict]:
        url = f"{_BASE}/v2/snapshot/locale/us/markets/stocks/tickers"
        body = self._get(url, {"tickers": ",".join(tickers)})
        return {item["ticker"]: item for item in (body.get("tickers") or [])}

    @with_backoff(max_attempts=5, base_wait=2.0)
    def _get(self, url: str, params: dict) -> dict:
        """
        Execute a GET request, inject the API key, check for application-level
        errors, and raise on HTTP errors. The @with_backoff decorator handles 429s.
        """
        full_params = {**params, "apiKey": self._key}
        r = requests.get(url, params=full_params, timeout=15)
        if r.status_code == 429:
            raise _RateLimitError("Massive API rate limit")
        r.raise_for_status()
        body = r.json()
        if body.get("status") == "ERROR":
            raise RuntimeError(f"Massive API error: {body.get('error')} — url={url}")
        return body

    @staticmethod
    def _to_df(raw: list[dict]) -> pd.DataFrame:
        """Convert a list of Polygon bar dicts to the standard DataFrame schema."""
        if not raw:
            return pd.DataFrame(
                columns=["date", "open", "high", "low", "close", "volume", "vwap"]
            )
        df = pd.DataFrame(raw)
        df["date"] = (
            pd.to_datetime(df["t"], unit="ms", utc=True)
            .dt.tz_convert("America/New_York")
            .dt.normalize()
        )
        df = df.rename(columns={
            "o": "open", "h": "high", "l": "low",
            "c": "close", "v": "volume", "vw": "vwap",
        })
        return (
            df[["date", "open", "high", "low", "close", "volume", "vwap"]]
            .reset_index(drop=True)
        )


class _RateLimitError(Exception):
    """Sentinel for 429 responses so the retry decorator can match it."""
```

### Timestamp conversion deep-dive

Polygon returns bar timestamps as **Unix milliseconds UTC** for the *start* of
the bar period. For a daily bar dated 2024-01-15 ET, the `t` field is
`1705276800000` (midnight UTC on that date). After converting to
`America/New_York` and normalising (stripping the time component), the result is
`2024-01-15 00:00:00-05:00`, which compares correctly against `date(2024, 1, 15)`.

```python
# Worked example
import pandas as pd
t_ms = 1705276800000
ts = pd.Timestamp(t_ms, unit="ms", utc=True)
# Timestamp('2024-01-15 00:00:00+0000', tz='UTC')
ts_ny = ts.tz_convert("America/New_York")
# Timestamp('2024-01-14 19:00:00-0500', tz='America/New_York')
# ↑ This is 7 pm ET on Jan 14 — Polygon midnight UTC = ET afternoon of the prior day.
# normalize() moves it back to midnight on the ET date:
ts_ny.normalize()
# Timestamp('2024-01-14 00:00:00-0500', tz='America/New_York')
```

**Gotcha**: Polygon's midnight UTC encodes the *business date in ET* but only
when using the `day` timespan — for intraday timespans the timestamp is the
literal start of the minute/hour bar in UTC. The `.normalize()` call is
safe for daily bars and should be skipped for intraday bars.

---

## 5. Market Simulator — `market_simulator.py`

Used when `MASSIVE_API_KEY` is absent. Covers three situations:

1. **CI / unit tests** — reproducible, no network needed.
2. **Offline development** — build features or the backtester without burning API quota.
3. **Backtester replay** — after `yfinance_loader` has populated `price_bars`, the
   simulator reads from the DB rather than generating synthetic data.

### Two-mode selection logic

```
get_bars(ticker, from_date, to_date)
        │
        ├── db_session provided AND price_bars has rows for (ticker, range)?
        │        YES ──► DB Replay Mode  (real adjusted prices, no network)
        │        NO  ──► Synthetic Mode  (GBM random walk, deterministic)
        │
        └── Returns identical DataFrame schema either way
```

### GBM price generation

Geometric Brownian Motion (the Black-Scholes equity model):

```
S(t+1) = S(t) · exp( (μ − σ²/2) · Δt  +  σ · √Δt · Z )
  Z ~ N(0, 1),  Δt = 1 (one trading day)
```

- `μ` = daily drift (annualised drift / 252)
- `σ` = daily volatility (annualised vol / √252)
- Using `exp(cumsum(...))` vectorises the path across N days in one call.
- Seed is derived from a hash of the ticker string, so each ticker always
  produces the same path regardless of what other tickers are requested.

```python
# backend/app/services/data_ingestion/market_simulator.py

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from .market_interface import Bar, Quote


# ---------------------------------------------------------------------------
# Per-ticker GBM parameters
# ---------------------------------------------------------------------------

@dataclass
class _TickerParams:
    seed:        int
    start_price: float
    mu:          float    # daily drift  (annualised / 252)
    sigma:       float    # daily vol    (annualised / sqrt(252))


_KNOWN: dict[str, _TickerParams] = {
    "AAPL":  _TickerParams(1001, 185.0, 0.0010, 0.014),
    "MSFT":  _TickerParams(1002, 375.0, 0.0011, 0.013),
    "NVDA":  _TickerParams(1003, 490.0, 0.0020, 0.025),
    "GOOGL": _TickerParams(1004, 140.0, 0.0008, 0.014),
    "AMZN":  _TickerParams(1005, 180.0, 0.0009, 0.016),
    "META":  _TickerParams(1006, 480.0, 0.0012, 0.018),
    "TSLA":  _TickerParams(1007, 250.0, 0.0005, 0.030),
    "SPY":   _TickerParams(2001, 450.0, 0.0005, 0.008),
    "QQQ":   _TickerParams(2002, 380.0, 0.0006, 0.010),
    "BRK.B": _TickerParams(2003, 360.0, 0.0006, 0.009),
    "AMGN":  _TickerParams(3001, 280.0, 0.0006, 0.012),
    "JNJ":   _TickerParams(3002, 155.0, 0.0004, 0.010),
    "JPM":   _TickerParams(3003, 195.0, 0.0007, 0.013),
    "XOM":   _TickerParams(3004, 110.0, 0.0005, 0.014),
}

_DEFAULTS = _TickerParams(seed=0, start_price=100.0, mu=0.0008, sigma=0.015)


def _params_for(ticker: str) -> _TickerParams:
    if ticker in _KNOWN:
        return _KNOWN[ticker]
    # Deterministic hash → reproducible seed and starting price for unknown tickers
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
    Provides OHLCV data via DB replay or GBM synthesis.

    All public methods return the same schema as MassiveProvider so that
    SimulatorProvider can delegate to this class transparently.
    """

    # All synthetic series are generated starting from this origin date.
    # Requesting from_date < _SIM_ORIGIN still works; the path simply starts here.
    _SIM_ORIGIN = date(2019, 1, 2)

    def __init__(self, db_session=None, seed: int = 42) -> None:
        self._db = db_session
        self._seed = seed

    # ------------------------------------------------------------------
    # Public API
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
        df = self.get_bars(ticker, date.today() - timedelta(days=10), date.today())
        if df.empty:
            p = _params_for(ticker).start_price
            return Bar(ticker=ticker, date=date.today(),
                       open=p, high=p, low=p, close=p, volume=1_000_000, vwap=p)
        row = df.iloc[-1]
        return Bar(
            ticker=ticker,
            date=row["date"].date() if hasattr(row["date"], "date") else row["date"],
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=int(row["volume"]),
            vwap=float(row["vwap"]) if row["vwap"] is not None else None,
        )

    def latest_quote(self, ticker: str) -> Quote:
        """Synthesise a 2 bps spread around the last close."""
        bar = self.latest_bar(ticker)
        spread = bar.close * 0.0002
        return Quote(
            ticker=ticker,
            bid=round(bar.close - spread / 2, 4),
            ask=round(bar.close + spread / 2, 4),
            bid_size=100,
            ask_size=100,
            timestamp=pd.Timestamp.utcnow(),
        )

    def daily_summary(self, as_of: date) -> dict[str, Bar]:
        """Return one Bar per known ticker for a given date."""
        return {t: self.latest_bar(t) for t in _KNOWN}

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
                WHERE  i.symbol     = :ticker
                  AND  pb.timeframe  = :tf
                  AND  pb.timestamp >= :from_ts
                  AND  pb.timestamp <= :to_ts
                ORDER BY pb.timestamp ASC
            """),
            {
                "ticker":  ticker,
                "tf":      tf,
                "from_ts": pd.Timestamp(from_date, tz="UTC"),
                "to_ts":   pd.Timestamp(to_date,   tz="UTC") + pd.Timedelta(days=1),
            },
        ).fetchall()

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
        df["date"] = (
            pd.to_datetime(df["date"], utc=True)
            .dt.tz_convert("America/New_York")
            .dt.normalize()
        )
        df["vwap"] = None
        return df[["date", "open", "high", "low", "close", "volume", "vwap"]].reset_index(drop=True)

    # ------------------------------------------------------------------
    # Synthetic GBM
    # ------------------------------------------------------------------

    def _synthetic_bars(self, ticker: str, from_date: date, to_date: date) -> pd.DataFrame:
        p = _params_for(ticker)
        # XOR the ticker seed with the instance seed so callers can vary the
        # overall random universe while keeping per-ticker relative ordering stable.
        rng = np.random.default_rng(p.seed ^ self._seed)

        # Generate the full path from _SIM_ORIGIN to to_date so that the
        # sub-series starting at from_date is always the same regardless of
        # what from_date was passed — this is the no-lookahead guarantee.
        bdays = pd.bdate_range(self._SIM_ORIGIN, to_date, freq="B")
        n = len(bdays)
        if n == 0:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "vwap"])

        # --- Closing prices via GBM ---
        log_returns = (
            (p.mu - 0.5 * p.sigma ** 2)
            + p.sigma * rng.standard_normal(n)
        )
        closes = p.start_price * np.exp(np.cumsum(log_returns))

        # --- Intraday OHLC from close ---
        intraday_vol = p.sigma * 0.7     # intraday moves ≈ 70% of close-to-close vol
        daily_range = np.abs(rng.normal(0, intraday_vol, n)) * closes

        opens = closes * np.exp(rng.normal(0, p.sigma * 0.3, n))
        up_frac = rng.uniform(0.2, 0.8, n)
        highs = np.maximum(opens, closes) + daily_range * up_frac
        lows  = np.minimum(opens, closes) - daily_range * (1 - up_frac)
        lows  = np.maximum(lows, 0.01)   # hard price floor

        volume = rng.lognormal(mean=np.log(5_000_000), sigma=0.5, size=n).astype(int)
        vwap   = (opens + highs + lows + closes) / 4   # typical-price approximation

        df = pd.DataFrame({
            "date":   bdays,
            "open":   np.round(opens,  4),
            "high":   np.round(highs,  4),
            "low":    np.round(lows,   4),
            "close":  np.round(closes, 4),
            "volume": volume,
            "vwap":   np.round(vwap,   4),
        })

        # Attach ET timezone and trim to the requested window
        df["date"] = df["date"].dt.tz_localize("America/New_York")
        from_ts = pd.Timestamp(from_date, tz="UTC").tz_convert("America/New_York")
        to_ts   = pd.Timestamp(to_date,   tz="UTC").tz_convert("America/New_York")
        mask = (df["date"] >= from_ts) & (df["date"] <= to_ts)
        return df[mask].reset_index(drop=True)
```

### GBM invariant table

| Property | How enforced |
|----------|-------------|
| `high >= open` | `np.maximum(opens, closes) + positive daily_range * fraction` |
| `high >= close` | same |
| `low <= open` | `np.minimum(opens, closes) - positive daily_range * (1-fraction)` |
| `low <= close` | same |
| `close > 0` | GBM exponential — can never reach zero |
| `low >= 0.01` | explicit floor |
| No lookahead | Full path always generated from `_SIM_ORIGIN`; window trimmed after |
| Determinism | Seed = `ticker_seed XOR instance_seed`; `np.random.default_rng` |

---

## 6. Simulator Provider — `simulator_provider.py`

A thin adapter that satisfies the `MarketDataProvider` ABC by delegating to
`MarketSimulator`. The only logic here is the multi-ticker loop.

```python
# backend/app/services/data_ingestion/simulator_provider.py

from __future__ import annotations

from datetime import date

import pandas as pd

from .market_interface import Bar, MarketDataProvider, Quote
from .market_simulator import MarketSimulator


class SimulatorProvider(MarketDataProvider):
    """
    Wraps MarketSimulator. DB replay is attempted first (when db_session is
    provided); synthetic GBM data is the fallback.
    """

    def __init__(self, db_session=None, seed: int = 42) -> None:
        self._sim = MarketSimulator(db_session=db_session, seed=seed)

    def get_bars(
        self,
        tickers: list[str],
        from_date: date,
        to_date: date,
        timespan: str = "day",
    ) -> dict[str, pd.DataFrame]:
        return {
            t: self._sim.get_bars(t, from_date, to_date, timespan)
            for t in tickers
        }

    def get_latest_quote(self, tickers: list[str]) -> dict[str, Quote]:
        return {t: self._sim.latest_quote(t) for t in tickers}

    def get_snapshot(self, tickers: list[str]) -> dict[str, Bar]:
        return {t: self._sim.latest_bar(t) for t in tickers}

    def get_daily_market_summary(self, as_of: date) -> dict[str, Bar]:
        return self._sim.daily_summary(as_of)
```

---

## 7. Historical Ingestion Loader — `yfinance_loader.py`

Used **once** to backfill 2–5 years of price history into `price_bars`. After
the initial load, incremental daily updates come from `alpaca_loader.py`.

`yfinance` is free, requires no API key, and returns adjusted prices by default
when `auto_adjust=True`. It does not need to be wrapped by the `MarketDataProvider`
ABC because it is only ever called from the ingestion job, never from feature
engineering or the backtester.

```python
# backend/app/services/data_ingestion/yfinance_loader.py

from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd
import yfinance as yf
from sqlalchemy.orm import Session

from .db_writer import upsert_price_bars

logger = logging.getLogger(__name__)

# Default watchlist — extend in .env as WATCHLIST=AAPL,MSFT,...
DEFAULT_WATCHLIST = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
    "META", "TSLA", "SPY", "QQQ", "BRK-B",
    "JPM", "JNJ", "XOM", "AMGN",
]

# yfinance uses "BRK-B" but most other systems use "BRK.B" — normalise on ingest
_YF_TO_CANONICAL: dict[str, str] = {"BRK-B": "BRK.B"}
_CANONICAL_TO_YF: dict[str, str] = {v: k for k, v in _YF_TO_CANONICAL.items()}


def backfill_watchlist(
    db: Session,
    watchlist: list[str] | None = None,
    years: int = 5,
) -> dict[str, int]:
    """
    Pull `years` years of adjusted daily OHLCV for every symbol in `watchlist`
    and upsert into price_bars. Returns {symbol: rows_upserted}.

    Called once at project setup and never again (incremental updates via alpaca_loader).
    """
    symbols = watchlist or DEFAULT_WATCHLIST
    to_date   = date.today()
    from_date = to_date - timedelta(days=years * 365)

    results: dict[str, int] = {}
    for symbol in symbols:
        yf_ticker = _CANONICAL_TO_YF.get(symbol, symbol)
        try:
            df = _download_one(yf_ticker, from_date, to_date)
            if df.empty:
                logger.warning("yfinance returned no data for %s", symbol)
                results[symbol] = 0
                continue
            df["symbol"] = symbol   # store canonical symbol
            n = upsert_price_bars(db, df, timeframe="1d")
            logger.info("Backfilled %s: %d bars", symbol, n)
            results[symbol] = n
        except Exception:
            logger.exception("Failed to backfill %s", symbol)
            results[symbol] = -1

    return results


def _download_one(yf_ticker: str, from_date: date, to_date: date) -> pd.DataFrame:
    """
    Download daily bars for one ticker and return a normalised DataFrame.

    Columns returned: date (DatetimeTZDtype, America/New_York), open, high,
                      low, close, volume.

    yfinance returns 'Adj Close' when auto_adjust=True; close == adj_close.
    The 'Dividends' and 'Stock Splits' columns are dropped.
    """
    raw = yf.download(
        yf_ticker,
        start=from_date.isoformat(),
        end=(to_date + timedelta(days=1)).isoformat(),   # yfinance end is exclusive
        auto_adjust=True,
        progress=False,
        threads=False,
    )

    if raw.empty:
        return pd.DataFrame()

    # yfinance returns a MultiIndex if multiple tickers are downloaded together.
    # Single-ticker download returns a simple column Index.
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.droplevel(1)

    raw = raw.rename(columns={
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume",
    })
    raw = raw[["open", "high", "low", "close", "volume"]].copy()

    # The index is a DatetimeTZDtype in UTC from recent yfinance versions;
    # older versions return tz-naive. Normalise both.
    if raw.index.tz is None:
        raw.index = raw.index.tz_localize("UTC")
    raw.index = raw.index.tz_convert("America/New_York").normalize()
    raw.index.name = "date"
    raw = raw.reset_index()
    raw = raw.dropna(subset=["close"])   # yfinance may insert NaN rows on holidays
    return raw
```

### Adjusted-price rule

`auto_adjust=True` in yfinance replaces the raw `Close` column with the
split-and-dividend adjusted close, and adjusts `Open`/`High`/`Low` by the
same ratio. **Never use `auto_adjust=False`** — raw close prices produce phantom
signals around split and dividend dates (D17 in the design decisions table).

---

## 8. News Loader — `news_loader.py`

Pulls the latest headlines per symbol via the [NewsAPI](https://newsapi.org) free tier
(100 requests/day). Headlines are stored in `news_articles` with a strict
`published_at <= as_of_date` filter to prevent future news from leaking into
the backtest (D5 in design decisions).

```python
# backend/app/services/data_ingestion/news_loader.py

from __future__ import annotations

import logging
import os
from datetime import date, timedelta

import requests
from sqlalchemy.orm import Session

from app.models.news_article import NewsArticle
from app.db.session import get_db_instrument_id

logger = logging.getLogger(__name__)

_BASE = "https://newsapi.org/v2"
_KEY  = os.environ.get("NEWS_API_KEY", "")


def fetch_headlines_for_symbol(
    symbol: str,
    as_of: date,
    db: Session,
    lookback_days: int = 3,
    page_size: int = 5,
) -> list[dict]:
    """
    Fetch up to `page_size` headlines for `symbol` published between
    (as_of - lookback_days) and as_of (inclusive). Upserts into news_articles.

    IMPORTANT: as_of is the decision date. Never pass date.today() from backtest
    code — always pass the loop's current date D so no future news leaks in.

    Returns a list of dicts with keys: headline, published_at, source, url, summary.
    """
    from_dt = as_of - timedelta(days=lookback_days)
    params = {
        "q":        symbol,
        "from":     from_dt.isoformat(),
        "to":       as_of.isoformat(),
        "language": "en",
        "sortBy":   "publishedAt",
        "pageSize": page_size,
        "apiKey":   _KEY,
    }

    try:
        r = requests.get(f"{_BASE}/everything", params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception:
        logger.exception("NewsAPI request failed for %s", symbol)
        return []

    articles = data.get("articles") or []
    results = []

    instrument_id = get_db_instrument_id(db, symbol)
    for art in articles:
        pub = art.get("publishedAt", "")[:10]   # "YYYY-MM-DD"
        row = {
            "headline":    art.get("title", ""),
            "summary":     art.get("description") or "",
            "source":      art.get("source", {}).get("name", ""),
            "url":         art.get("url", ""),
            "published_at": pub,
        }
        results.append(row)
        _upsert_article(db, instrument_id, row)

    db.commit()
    return results


def _upsert_article(db: Session, instrument_id: int, row: dict) -> None:
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    stmt = pg_insert(NewsArticle.__table__).values(
        instrument_id=instrument_id,
        published_at=row["published_at"],
        headline=row["headline"],
        summary=row["summary"],
        source=row["source"],
        url=row["url"],
    ).on_conflict_do_nothing(index_elements=["url"])
    db.execute(stmt)
```

### Backtester anti-lookahead rule

When building the LLM context for decision date D, always pass `as_of=D` to
`fetch_headlines_for_symbol`. Never pass `date.today()`. The DB query in the
LLM context assembly layer should also filter `published_at <= D` as a
second safeguard.

---

## 9. Live/Daily Ingestion — `alpaca_loader.py`

After the historical backfill (yfinance), daily incremental ingest runs via
the Alpaca Market Data API. This keeps `price_bars` current without consuming
NewsAPI or Polygon quota for individual bars.

```python
# backend/app/services/data_ingestion/alpaca_loader.py

from __future__ import annotations

import logging
import os
from datetime import date, timedelta

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from sqlalchemy.orm import Session

from .db_writer import upsert_price_bars

logger = logging.getLogger(__name__)


def _alpaca_client() -> StockHistoricalDataClient:
    return StockHistoricalDataClient(
        api_key=os.environ["ALPACA_API_KEY"],
        secret_key=os.environ["ALPACA_SECRET_KEY"],
    )


def ingest_daily_bars(
    db: Session,
    watchlist: list[str],
    as_of: date | None = None,
) -> dict[str, int]:
    """
    Pull yesterday's (or `as_of`'s) adjusted daily bar for each symbol and
    upsert into price_bars. Called by the daily scheduled job after market close.

    Returns {symbol: 1 if upserted, 0 if no data}.
    """
    target = as_of or (date.today() - timedelta(days=1))
    client = _alpaca_client()

    request = StockBarsRequest(
        symbol_or_symbols=watchlist,
        timeframe=TimeFrame.Day,
        start=pd.Timestamp(target),
        end=pd.Timestamp(target) + pd.Timedelta(days=1),
        adjustment="all",   # split + dividend adjusted
    )

    try:
        bars = client.get_stock_bars(request).df
    except Exception:
        logger.exception("Alpaca bar request failed for %s", target)
        return {s: 0 for s in watchlist}

    if bars.empty:
        logger.warning("Alpaca returned no bars for %s", target)
        return {s: 0 for s in watchlist}

    # alpaca-py returns a MultiIndex (symbol, timestamp) — reset for processing
    bars = bars.reset_index()
    bars = bars.rename(columns={
        "symbol": "symbol", "timestamp": "date",
        "open": "open", "high": "high", "low": "low",
        "close": "close", "volume": "volume", "vwap": "vwap",
    })
    bars["date"] = pd.to_datetime(bars["date"], utc=True).dt.tz_convert("America/New_York").dt.normalize()

    results: dict[str, int] = {}
    for symbol in watchlist:
        sub = bars[bars["symbol"] == symbol]
        if sub.empty:
            results[symbol] = 0
            continue
        n = upsert_price_bars(db, sub, timeframe="1d")
        results[symbol] = n

    return results
```

---

## 10. Database Upsert Helpers — `db_writer.py`

Centralises the logic for writing price data to `price_bars` so both loaders
share the same upsert semantics.

```python
# backend/app/services/data_ingestion/db_writer.py

from __future__ import annotations

import logging
from typing import Sequence

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def upsert_price_bars(
    db: Session,
    df: pd.DataFrame,
    timeframe: str = "1d",
) -> int:
    """
    Upsert rows from `df` into price_bars using PostgreSQL INSERT ... ON CONFLICT DO UPDATE.

    `df` must contain columns: symbol (str), date (Timestamp, tz-aware),
    open, high, low, close, volume. `vwap` is optional.

    Returns the number of rows upserted.
    """
    if df.empty:
        return 0

    # Resolve instrument_id for each unique symbol
    symbols = df["symbol"].unique().tolist()
    sym_to_id = _get_instrument_ids(db, symbols)

    rows_written = 0
    for _, row in df.iterrows():
        inst_id = sym_to_id.get(row["symbol"])
        if inst_id is None:
            logger.warning("Unknown symbol %s — skipping", row["symbol"])
            continue

        db.execute(
            text("""
                INSERT INTO price_bars
                    (instrument_id, timestamp, timeframe, open, high, low, close, volume, vwap)
                VALUES
                    (:inst_id, :ts, :tf, :open, :high, :low, :close, :volume, :vwap)
                ON CONFLICT (instrument_id, timestamp, timeframe)
                DO UPDATE SET
                    open   = EXCLUDED.open,
                    high   = EXCLUDED.high,
                    low    = EXCLUDED.low,
                    close  = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    vwap   = EXCLUDED.vwap
            """),
            {
                "inst_id": inst_id,
                "ts":      pd.Timestamp(row["date"]).tz_convert("UTC"),
                "tf":      timeframe,
                "open":    float(row["open"]),
                "high":    float(row["high"]),
                "low":     float(row["low"]),
                "close":   float(row["close"]),
                "volume":  int(row["volume"]),
                "vwap":    float(row["vwap"]) if "vwap" in row and pd.notna(row["vwap"]) else None,
            },
        )
        rows_written += 1

    db.commit()
    return rows_written


def _get_instrument_ids(db: Session, symbols: list[str]) -> dict[str, int]:
    if not symbols:
        return {}
    rows = db.execute(
        text("SELECT symbol, id FROM instruments WHERE symbol = ANY(:syms)"),
        {"syms": symbols},
    ).fetchall()
    return {r[0]: r[1] for r in rows}
```

### Performance note

For bulk historical ingest (thousands of rows), swap the row-by-row loop for a
batch insert using `psycopg2.extras.execute_values` or SQLAlchemy Core's
`insert().values(...)`. The loop-per-row version is fine for daily incremental
updates (≤20 rows/day for a typical watchlist).

---

## 11. Rate-Limit & Retry Utilities — `retry.py`

```python
# backend/app/services/data_ingestion/retry.py

from __future__ import annotations

import functools
import logging
import time
from typing import Callable, Type

logger = logging.getLogger(__name__)


def with_backoff(
    max_attempts: int = 5,
    base_wait: float = 2.0,
    exceptions: tuple[Type[Exception], ...] = (Exception,),
) -> Callable:
    """
    Decorator: retry on any exception in `exceptions` with exponential back-off.
    Delays: base_wait, base_wait*2, base_wait*4, ...

    Usage:
        @with_backoff(max_attempts=5, base_wait=2.0)
        def _get(self, url, params): ...
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    wait = base_wait * (2 ** attempt)
                    logger.warning(
                        "%s attempt %d/%d failed (%s); retrying in %.1fs",
                        fn.__name__, attempt + 1, max_attempts, exc, wait,
                    )
                    time.sleep(wait)
            raise RuntimeError(
                f"{fn.__name__} failed after {max_attempts} attempts"
            ) from last_exc
        return wrapper
    return decorator
```

Alternative: use `tenacity` (already in requirements) for more expressive retry
logic including jitter, which is recommended for high-concurrency scenarios:

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    retry=retry_if_exception_type((requests.HTTPError, _RateLimitError)),
    reraise=True,
)
def _get(self, url: str, params: dict) -> dict:
    ...
```

Use `tenacity` in the LLM reasoning layer (where it is already mandated by the
plan) and the simpler decorator above for the Massive provider — consistency
within each module matters more than uniformity across modules.

---

## 12. FastAPI Wiring — ingestion endpoints

```python
# backend/app/api/ingestion.py

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.data_ingestion.yfinance_loader import backfill_watchlist, DEFAULT_WATCHLIST
from app.services.data_ingestion.alpaca_loader import ingest_daily_bars
from app.services.data_ingestion.news_loader import fetch_headlines_for_symbol
from app.services.data_ingestion.market_interface import create_provider

router = APIRouter(prefix="/ingestion", tags=["ingestion"])

DbDep = Annotated[Session, Depends(get_db)]


@router.post("/backfill")
def trigger_backfill(
    db: DbDep,
    years: int = Query(default=5, ge=1, le=10),
    watchlist: list[str] = Query(default=DEFAULT_WATCHLIST),
):
    """
    Trigger a historical backfill via yfinance. Idempotent — safe to re-run;
    existing rows are updated (ON CONFLICT DO UPDATE).
    """
    results = backfill_watchlist(db, watchlist=watchlist, years=years)
    return {"status": "ok", "rows_upserted": results}


@router.post("/daily")
def trigger_daily_ingest(
    db: DbDep,
    as_of: date | None = Query(default=None),
    watchlist: list[str] = Query(default=DEFAULT_WATCHLIST),
):
    """Run the incremental daily ingest for yesterday (or as_of)."""
    results = ingest_daily_bars(db, watchlist=watchlist, as_of=as_of)
    return {"status": "ok", "rows_upserted": results}


@router.get("/bars/{symbol}")
def get_bars(
    symbol: str,
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: DbDep = None,
):
    """
    Return OHLCV bars for one symbol from the market data layer.
    Uses MassiveProvider if MASSIVE_API_KEY is set, else SimulatorProvider.
    This endpoint is primarily for debugging — the feature layer reads via
    create_provider() internally.
    """
    provider = create_provider(db_session=db)
    bars = provider.get_bars([symbol], from_date, to_date)
    df = bars.get(symbol)
    if df is None or df.empty:
        raise HTTPException(status_code=404, detail=f"No bars for {symbol}")
    return df.to_dict(orient="records")


@router.get("/snapshot")
def get_snapshot(
    tickers: list[str] = Query(...),
    db: DbDep = None,
):
    """Return the most recent EOD bar per ticker."""
    provider = create_provider(db_session=db)
    snaps = provider.get_snapshot(tickers)
    return {t: vars(b) for t, b in snaps.items()}
```

Register the router in `main.py`:

```python
# backend/app/main.py (excerpt)
from app.api.ingestion import router as ingestion_router
app.include_router(ingestion_router)
```

---

## 13. Environment Variables

Add all of these to `.env.example` with placeholder values. Never commit `.env`.

```dotenv
# ── Database ────────────────────────────────────────────────────────────────
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/trading

# ── Alpaca Paper Trading ─────────────────────────────────────────────────────
ALPACA_API_KEY=your_alpaca_key_here
ALPACA_SECRET_KEY=your_alpaca_secret_here
ALPACA_BASE_URL=https://paper-api.alpaca.markets   # NEVER change this to live

# ── Massive/Polygon Market Data ───────────────────────────────────────────────
# Leave blank to use the market simulator (offline / CI mode)
MASSIVE_API_KEY=
MASSIVE_BASE_URL=https://api.polygon.io

# ── News ─────────────────────────────────────────────────────────────────────
NEWS_API_KEY=your_newsapi_key_here

# ── LLM (Cerebras) ───────────────────────────────────────────────────────────
LLM_API_KEY=your_cerebras_key_here
LLM_MODEL=gpt-oss-120b

# ── Risk parameters ──────────────────────────────────────────────────────────
MAX_POSITION_PCT=0.10
MAX_POSITIONS=8
DAILY_LOSS_LIMIT_PCT=0.03

# ── Watchlist ─────────────────────────────────────────────────────────────────
WATCHLIST=AAPL,MSFT,NVDA,GOOGL,AMZN,META,TSLA,SPY,QQQ,BRK.B,JPM,JNJ,XOM,AMGN
```

### Provider selection at a glance

| `MASSIVE_API_KEY` | Provider used |
|-------------------|--------------|
| Set to a real key | `MassiveProvider` — live Polygon REST API |
| Blank or unset | `SimulatorProvider` — DB replay → GBM fallback |

---

## 14. Testing Strategy & Test Fixtures

### Guiding rule

**Never set `MASSIVE_API_KEY` in the test environment.** All unit and integration
tests use `SimulatorProvider` by default. Tests that need real market data are
tagged `@pytest.mark.integration` and skipped in CI.

### Conftest fixtures

```python
# tests/backend/conftest.py

import pytest
from unittest.mock import MagicMock, patch
from datetime import date

from app.services.data_ingestion.market_interface import create_provider
from app.services.data_ingestion.simulator_provider import SimulatorProvider
from app.services.data_ingestion.market_simulator import MarketSimulator


@pytest.fixture
def sim() -> MarketSimulator:
    """A fresh simulator with no DB session and seed=42."""
    return MarketSimulator(db_session=None, seed=42)


@pytest.fixture
def sim_provider() -> SimulatorProvider:
    return SimulatorProvider(db_session=None, seed=42)


@pytest.fixture
def mock_massive_get():
    """
    Patch MassiveProvider._get() to return a canned payload.
    Use in tests that verify how MassiveProvider processes API responses.
    """
    with patch(
        "app.services.data_ingestion.massive_provider.MassiveProvider._get"
    ) as mock:
        yield mock
```

### Simulator unit tests

```python
# tests/backend/test_market_simulator.py

import pandas as pd
import pytest
from datetime import date

from app.services.data_ingestion.market_simulator import MarketSimulator

SIM = MarketSimulator(db_session=None, seed=42)


class TestSchema:
    def test_columns(self):
        df = SIM.get_bars("AAPL", date(2023, 1, 1), date(2023, 3, 31))
        assert list(df.columns) == ["date", "open", "high", "low", "close", "volume", "vwap"]

    def test_non_empty(self):
        df = SIM.get_bars("AAPL", date(2023, 1, 1), date(2023, 3, 31))
        assert len(df) > 0

    def test_unknown_ticker_falls_back(self):
        df = SIM.get_bars("XYZFAKE99", date(2023, 1, 1), date(2023, 3, 31))
        assert len(df) > 0


class TestNoLookahead:
    def test_date_upper_bound(self):
        to = date(2023, 6, 15)
        df = SIM.get_bars("AAPL", date(2023, 1, 1), to)
        assert df["date"].dt.date.max() <= to


class TestOHLCInvariants:
    @pytest.fixture(autouse=True)
    def df(self):
        self._df = SIM.get_bars("MSFT", date(2022, 1, 1), date(2022, 12, 31))

    def test_high_gte_open(self):
        assert (self._df["high"] >= self._df["open"]).all()

    def test_high_gte_close(self):
        assert (self._df["high"] >= self._df["close"]).all()

    def test_low_lte_open(self):
        assert (self._df["low"] <= self._df["open"]).all()

    def test_low_lte_close(self):
        assert (self._df["low"] <= self._df["close"]).all()

    def test_positive_prices(self):
        assert (self._df["close"] > 0).all()
        assert (self._df["low"] >= 0.01).all()


class TestDeterminism:
    def test_same_seed_same_path(self):
        df1 = SIM.get_bars("NVDA", date(2023, 1, 1), date(2023, 6, 30))
        df2 = MarketSimulator(seed=42).get_bars("NVDA", date(2023, 1, 1), date(2023, 6, 30))
        pd.testing.assert_frame_equal(df1, df2)

    def test_different_seed_different_path(self):
        df1 = SIM.get_bars("AAPL", date(2023, 1, 1), date(2023, 6, 30))
        df2 = MarketSimulator(seed=99).get_bars("AAPL", date(2023, 1, 1), date(2023, 6, 30))
        assert not df1["close"].equals(df2["close"])
```

### Factory / provider-selection tests

```python
# tests/backend/test_market_interface.py

import pytest
from app.services.data_ingestion.market_interface import create_provider
from app.services.data_ingestion.simulator_provider import SimulatorProvider
from app.services.data_ingestion.massive_provider import MassiveProvider


def test_returns_simulator_without_key(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    assert isinstance(create_provider(), SimulatorProvider)


def test_returns_massive_with_key(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "fake_key")
    assert isinstance(create_provider(), MassiveProvider)


def test_simulator_schema_matches_contract(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    from datetime import date
    provider = create_provider()
    bars = provider.get_bars(["AAPL"], date(2023, 1, 1), date(2023, 3, 31))
    df = bars["AAPL"]
    assert set(df.columns) >= {"date", "open", "high", "low", "close", "volume", "vwap"}
```

### MassiveProvider response-parsing tests (mocked)

```python
# tests/backend/test_massive_provider.py

import pytest
from unittest.mock import patch
from datetime import date

from app.services.data_ingestion.massive_provider import MassiveProvider


SAMPLE_BARS_RESPONSE = {
    "status": "OK",
    "results": [
        {"t": 1672531200000, "o": 130.28, "h": 133.41, "l": 129.89, "c": 131.86,
         "v": 69458525, "vw": 131.6, "n": 400124},
        {"t": 1672617600000, "o": 126.89, "h": 128.66, "l": 125.08, "c": 125.07,
         "v": 70790813, "vw": 126.56, "n": 375149},
    ],
}


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "test_key")
    return MassiveProvider(api_key="test_key")


def test_get_bars_parses_response(provider):
    with patch.object(provider, "_get", return_value=SAMPLE_BARS_RESPONSE):
        bars = provider.get_bars(["AAPL"], date(2023, 1, 2), date(2023, 1, 3))
    df = bars["AAPL"]
    assert len(df) == 2
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume", "vwap"]
    assert df["close"].iloc[0] == pytest.approx(131.86)


def test_empty_response_returns_empty_df(provider):
    with patch.object(provider, "_get", return_value={"status": "OK", "results": []}):
        bars = provider.get_bars(["AAPL"], date(2023, 1, 2), date(2023, 1, 3))
    assert bars["AAPL"].empty


def test_api_error_raises(provider):
    with patch.object(provider, "_get", return_value={"status": "ERROR", "error": "Not found"}):
        with pytest.raises(RuntimeError, match="Massive API error"):
            provider._get("http://fake", {})
```

### Running the tests

```bash
# From project root
cd backend
source venv/bin/activate

# All market data tests
pytest tests/backend/test_market_simulator.py tests/backend/test_market_interface.py \
       tests/backend/test_massive_provider.py -v

# Full suite (excluding integration tests that need real API keys)
pytest tests/backend/ -v -m "not integration"
```

---

## 15. Operational Runbook

### First-time setup

```bash
# 1. Copy and fill in .env
cp .env.example .env
# Edit .env: add Alpaca keys, Cerebras key, NewsAPI key.
# Leave MASSIVE_API_KEY blank to start — SimulatorProvider covers Phase 0-5.

# 2. Start Postgres (Docker or local)
docker run -d --name trading-pg -e POSTGRES_DB=trading \
  -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16

# 3. Run Alembic migrations
cd backend && source venv/bin/activate
alembic upgrade head

# 4. Historical backfill (run once; takes 2-5 minutes for 14 symbols × 5 years)
curl -X POST "http://localhost:8000/ingestion/backfill?years=5"
# Or directly:
python -c "
from app.db.session import SessionLocal
from app.services.data_ingestion.yfinance_loader import backfill_watchlist
db = SessionLocal()
print(backfill_watchlist(db))
db.close()
"
```

### Daily operations

```bash
# Triggered by the APScheduler job or a cron → FastAPI endpoint.
# After market close (e.g. 18:00 ET):
curl -X POST "http://localhost:8000/ingestion/daily"

# News fetch runs inside the daily decision pipeline (news_loader.py is called
# by the LLM context assembler, not as a standalone job).
```

### Switching to live Massive data

```bash
# Add the key to .env:
MASSIVE_API_KEY=your_real_key

# Restart the server — create_provider() picks up the env var at call time.
# No code changes required.
```

### Checking which provider is active

```python
import os
key = os.environ.get("MASSIVE_API_KEY")
print("MassiveProvider (live)" if key else "SimulatorProvider (offline/CI)")
```

### When the Starter plan quota runs out

The Starter plan allows ~5 requests/minute. The bulk historical fetch
(`_fetch_aggs`) makes one request per ticker and follows pagination cursors. For
a 14-symbol watchlist over 5 years (~1260 bars each), expect:

- ~14 requests to fetch all bars (each returns up to 50,000 rows — well under
  the limit for 5 years of daily data)
- At 5 req/min: ~3 minutes total

If you hit 429s, the `@with_backoff` decorator retries with exponential
back-off up to 5 times. After 5 failures it raises `RuntimeError`. Re-run the
backfill endpoint — it is idempotent.

---

## 16. Design Decisions Reference

| # | Decision | Choice | Where |
|---|----------|--------|-------|
| MD-1 | Provider selection mechanism | Environment variable (`MASSIVE_API_KEY`) checked at `create_provider()` call time | `market_interface.py` |
| MD-2 | Callers never import concrete providers | All imports go through `create_provider()` | Every consumer module |
| MD-3 | Simulator mode priority | DB replay first, GBM fallback | `market_simulator.py:get_bars` |
| MD-4 | GBM seed construction | `ticker_seed XOR instance_seed` | Ensures per-ticker stability while allowing overall universe variation |
| MD-5 | Timestamp normalisation | Always `.tz_convert("America/New_York").normalize()` for daily bars | `massive_provider._to_df`, `market_simulator._db_bars` |
| MD-6 | Adjusted prices | `auto_adjust=True` in yfinance; `adjusted=true` in Massive API params; `adjustment="all"` in alpaca-py | D17 in plan.md |
| MD-7 | Historical backfill tool | yfinance (free, no key) | `yfinance_loader.py` |
| MD-8 | Incremental daily ingest | Alpaca market data (key already needed for paper trading) | `alpaca_loader.py` |
| MD-9 | News anti-lookahead guard | `as_of` param always == backtest loop date D; DB query also filters `published_at <= D` | `news_loader.py`, LLM context assembly |
| MD-10 | Upsert strategy | `INSERT ... ON CONFLICT DO UPDATE` (PostgreSQL) | `db_writer.py` |
| MD-11 | Retry strategy | `@with_backoff` decorator for Massive; `tenacity` for LLM | `retry.py`, `llm_reasoning/` |
| MD-12 | Integration test gate | `@pytest.mark.integration` + skip if key absent | Test files |
| MD-13 | BRK-B ticker mapping | `BRK.B` (canonical) ↔ `BRK-B` (yfinance) normalised on ingest | `yfinance_loader.py:_YF_TO_CANONICAL` |
