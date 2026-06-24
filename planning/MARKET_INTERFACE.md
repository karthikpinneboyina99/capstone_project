# Market Data Interface

A unified Python interface for retrieving stock prices. The active provider is selected at import time:

- **`MASSIVE_API_KEY` is set** → `MassiveProvider` (live data via the Massive/Polygon REST API)
- **`MASSIVE_API_KEY` is not set** → `SimulatorProvider` (deterministic replay from the `price_bars` DB table, falling back to a random-walk generator when the DB has no data for the requested range)

All callers — feature engineering, the backtester, and the live executor — import from this module and never call the Massive API directly. This is the only place that knows about `MASSIVE_API_KEY`.

---

## Interface Contract

```python
# backend/app/services/data_ingestion/market_interface.py

from __future__ import annotations
import abc
import os
from dataclasses import dataclass
from datetime import date
import pandas as pd


@dataclass(frozen=True)
class Bar:
    """One OHLCV bar. Prices are always split-and-dividend adjusted."""
    ticker:    str
    date:      date          # trading date (ET)
    open:      float
    high:      float
    low:       float
    close:     float
    volume:    int
    vwap:      float | None  # None if not available (simulator may omit)


@dataclass(frozen=True)
class Quote:
    """Best bid/ask at a point in time. Only available from MassiveProvider (Advanced plan)."""
    ticker:    str
    bid:       float
    ask:       float
    bid_size:  int
    ask_size:  int
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
```

---

## MassiveProvider

Uses the Massive REST API (see `MASSIVE_API.md`). Requires `MASSIVE_API_KEY`.

```python
# backend/app/services/data_ingestion/massive_provider.py

from __future__ import annotations
import os, time
import requests
import pandas as pd
from datetime import date
from .market_interface import MarketDataProvider, Bar, Quote

_BASE = "https://api.polygon.io"
_TIMESPAN_MAP = {"day": "day", "minute": "minute", "hour": "hour"}


class MassiveProvider(MarketDataProvider):
    def __init__(self, api_key: str | None = None) -> None:
        self._key = api_key or os.environ["MASSIVE_API_KEY"]

    # ------------------------------------------------------------------
    def get_bars(
        self,
        tickers: list[str],
        from_date: date,
        to_date: date,
        timespan: str = "day",
    ) -> dict[str, pd.DataFrame]:
        results = {}
        for ticker in tickers:
            raw = self._fetch_aggs(ticker, from_date, to_date, timespan)
            results[ticker] = self._to_df(ticker, raw)
        return results

    def get_latest_quote(self, tickers: list[str]) -> dict[str, Quote]:
        snaps = self._get_snapshots(tickers)
        out = {}
        for ticker, snap in snaps.items():
            lt = snap.get("lastQuote") or {}
            out[ticker] = Quote(
                ticker=ticker,
                bid=lt.get("P", 0.0),
                ask=lt.get("P", 0.0),     # Starter plan: bid == ask == last trade price
                bid_size=lt.get("S", 0),
                ask_size=lt.get("S", 0),
                timestamp=pd.Timestamp(snap.get("updated", 0), unit="ns", tz="UTC"),
            )
        return out

    def get_snapshot(self, tickers: list[str]) -> dict[str, Bar]:
        snaps = self._get_snapshots(tickers)
        out = {}
        for ticker, snap in snaps.items():
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
        url = f"{_BASE}/v2/aggs/grouped/locale/global/market/stocks/{as_of}"
        raw = self._get(url, {"adjusted": "true"})
        out = {}
        for item in raw.get("results") or []:
            t = item.get("T", "")
            out[t] = Bar(
                ticker=t,
                date=as_of,
                open=item["o"], high=item["h"], low=item["l"], close=item["c"],
                volume=int(item["v"]), vwap=item.get("vw"),
            )
        return out

    # ------------------------------------------------------------------  internals

    def _fetch_aggs(self, ticker, from_date, to_date, timespan) -> list[dict]:
        url = f"{_BASE}/v2/aggs/ticker/{ticker}/range/1/{timespan}/{from_date}/{to_date}"
        params = {"adjusted": "true", "sort": "asc", "limit": 50000}
        results = []
        while url:
            body = self._get(url, params)
            results.extend(body.get("results") or [])
            url = body.get("next_url")
            params = {}
        return results

    def _get_snapshots(self, tickers: list[str]) -> dict:
        url = f"{_BASE}/v2/snapshot/locale/us/markets/stocks/tickers"
        body = self._get(url, {"tickers": ",".join(tickers)})
        return {item["ticker"]: item for item in (body.get("tickers") or [])}

    def _get(self, url: str, params: dict) -> dict:
        params = {**params, "apiKey": self._key}
        for attempt in range(5):
            r = requests.get(url, params=params, timeout=15)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            body = r.json()
            if body.get("status") == "ERROR":
                raise RuntimeError(f"Massive API error: {body.get('error')}")
            return body
        raise RuntimeError("Massive API rate limit: max retries exceeded")

    @staticmethod
    def _to_df(ticker: str, raw: list[dict]) -> pd.DataFrame:
        if not raw:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "vwap"])
        df = pd.DataFrame(raw)
        df["date"] = (
            pd.to_datetime(df["t"], unit="ms", utc=True)
            .dt.tz_convert("America/New_York")
            .dt.normalize()
        )
        df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close",
                                 "v": "volume", "vw": "vwap"})
        return df[["date", "open", "high", "low", "close", "volume", "vwap"]].reset_index(drop=True)
```

---

## SimulatorProvider

Used when `MASSIVE_API_KEY` is absent (CI, unit tests, offline development). See `MARKET_SIMULATOR.md` for full design.

```python
# backend/app/services/data_ingestion/simulator_provider.py

from __future__ import annotations
from datetime import date
import pandas as pd
from .market_interface import MarketDataProvider, Bar, Quote
from .market_simulator import MarketSimulator   # see MARKET_SIMULATOR.md


class SimulatorProvider(MarketDataProvider):
    """
    Wraps MarketSimulator. Attempts DB replay first; falls back to
    random-walk generation if no price_bars rows exist for the range.
    """

    def __init__(self, db_session=None, seed: int = 42) -> None:
        self._sim = MarketSimulator(db_session=db_session, seed=seed)

    def get_bars(self, tickers, from_date, to_date, timespan="day") -> dict[str, pd.DataFrame]:
        return {t: self._sim.get_bars(t, from_date, to_date, timespan) for t in tickers}

    def get_latest_quote(self, tickers) -> dict[str, Quote]:
        return {t: self._sim.latest_quote(t) for t in tickers}

    def get_snapshot(self, tickers) -> dict[str, Bar]:
        return {t: self._sim.latest_bar(t) for t in tickers}

    def get_daily_market_summary(self, as_of: date) -> dict[str, Bar]:
        return self._sim.daily_summary(as_of)
```

---

## Factory Function

```python
# backend/app/services/data_ingestion/market_interface.py  (continued)

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
```

---

## Usage Pattern

```python
# Anywhere in the backend (feature engineering, backtester, executor)
from app.services.data_ingestion.market_interface import create_provider
from datetime import date

provider = create_provider(db_session=db)

# Fetch 2 years of daily bars for the watchlist
bars = provider.get_bars(
    tickers=["AAPL", "MSFT", "NVDA", "SPY", "QQQ"],
    from_date=date(2022, 1, 1),
    to_date=date(2023, 12, 31),
)
aapl_df = bars["AAPL"]   # pandas DataFrame with columns: date, open, high, low, close, volume, vwap

# Live snapshot (paper trading executor)
snaps = provider.get_snapshot(["AAPL", "MSFT"])
print(snaps["AAPL"].close)
```

---

## Environment Variable Reference

Add these to `.env.example`:

```
# Massive (formerly Polygon.io) API key — leave blank to use the simulator
MASSIVE_API_KEY=

# Optional: override the REST base URL (useful for testing against a local proxy)
MASSIVE_BASE_URL=https://api.polygon.io
```

---

## Testing Strategy

- Unit tests **always** use `SimulatorProvider` — never set `MASSIVE_API_KEY` in the test environment.
- Integration tests that need real market data are tagged `@pytest.mark.integration` and skipped in CI unless the key is present.
- `MassiveProvider._get()` can be patched in isolation tests to verify retry/backoff logic without hitting the network.

```python
# tests/backend/test_market_interface.py
import pytest
from unittest.mock import patch
from app.services.data_ingestion.market_interface import create_provider

def test_returns_simulator_without_key(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    from app.services.data_ingestion.simulator_provider import SimulatorProvider
    assert isinstance(create_provider(), SimulatorProvider)

def test_returns_massive_with_key(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "fake_key")
    from app.services.data_ingestion.massive_provider import MassiveProvider
    assert isinstance(create_provider(), MassiveProvider)
```
