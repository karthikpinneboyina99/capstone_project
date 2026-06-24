# Market Data Backend — Comprehensive Design Document

This document is the single implementation guide for the market data subsystem. It covers every component — from the wire-level data model to the SSE endpoint — and shows how they fit together. The three existing focused documents (`MARKET_INTERFACE.md`, `MARKET_SIMULATOR.md`, `MASSIVE_API.md`) remain the authoritative reference for their individual areas; this document adds the SSE layer, the in-process cache, FastAPI lifecycle wiring, and the full watchlist coordination flow.

---

## 1. Component Map

```
Watchlist (env / DB)
       │
       ▼
MarketDataSource (ABC)
  ├── MassiveProvider  ─── Massive/Polygon REST API ──► rate-limit backoff
  └── SimulatorProvider ─── DB replay → GBM fallback
       │
       ▼
PriceCache (thread-safe, version counter)
       │
       ├──► REST endpoints  (GET /prices, GET /snapshot)
       └──► SSE endpoint    (GET /stream/prices)
                │
                └──► React dashboard (EventSource)
```

---

## 2. PriceUpdate — Immutable Data Model

`PriceUpdate` carries a single real-time or end-of-day price event through the system. It is distinct from `Bar` (which is a full OHLCV record for historical storage) — `PriceUpdate` is the unit that flows through the cache and out the SSE stream.

```python
# backend/app/services/data_ingestion/price_update.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class PriceUpdate:
    """
    Immutable snapshot of a single ticker's price at a point in time.

    Frozen so instances can be safely shared across threads without copying.
    All timestamps are UTC.
    """
    ticker:    str
    price:     float          # last trade price or adjusted close
    bid:       float | None   # None when not available (EOD-only provider)
    ask:       float | None
    volume:    int            # accumulated volume for the current session
    timestamp: datetime       # tz-aware UTC

    # Derived helpers — computed at construction, not stored (frozen dataclass
    # with __post_init__ cannot mutate fields, so use properties).
    @property
    def mid(self) -> float:
        """Mid-price; falls back to last trade price when bid/ask absent."""
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2
        return self.price

    @property
    def spread(self) -> float | None:
        if self.bid is not None and self.ask is not None:
            return self.ask - self.bid
        return None

    def to_sse_dict(self) -> dict:
        """Serialise for JSON-encoded SSE payload."""
        return {
            "ticker":    self.ticker,
            "price":     self.price,
            "bid":       self.bid,
            "ask":       self.ask,
            "mid":       self.mid,
            "spread":    self.spread,
            "volume":    self.volume,
            "timestamp": self.timestamp.isoformat(),
        }


def price_update_from_bar(bar) -> PriceUpdate:
    """Construct a PriceUpdate from a Bar (EOD path — bid/ask unavailable)."""
    from datetime import date
    ts = datetime.combine(bar.date, datetime.min.time()).replace(tzinfo=timezone.utc)
    return PriceUpdate(
        ticker=bar.ticker,
        price=bar.close,
        bid=None,
        ask=None,
        volume=bar.volume,
        timestamp=ts,
    )


def price_update_from_quote(quote, last_price: float, volume: int = 0) -> PriceUpdate:
    """Construct a PriceUpdate from a Quote (intraday path)."""
    return PriceUpdate(
        ticker=quote.ticker,
        price=last_price,
        bid=quote.bid,
        ask=quote.ask,
        volume=volume,
        timestamp=quote.timestamp.to_pydatetime(),
    )
```

### Why frozen?

`frozen=True` makes every `PriceUpdate` immutable after construction. This is critical for correctness: the cache stores references, and SSE generator coroutines hold references for comparison. Without immutability, a coroutine could observe a partially-mutated object. Frozen dataclasses are also hashable by default (useful if we ever put them in a set for dedup).

---

## 3. PriceCache — Thread-Safe In-Process Store

`PriceCache` is the single in-memory source of truth for the latest price of every symbol on the watchlist. It uses a version counter rather than a per-symbol timestamp for SSE long-poll optimization: a client that sends `?since_version=42` will only receive a response when the global version exceeds 42, regardless of which symbols changed.

```python
# backend/app/services/data_ingestion/price_cache.py
from __future__ import annotations

import asyncio
import threading
from typing import Iterator

from .price_update import PriceUpdate


class PriceCache:
    """
    Thread-safe store of the most recent PriceUpdate per ticker.

    Version counter:
      - Starts at 0; incremented atomically on every write.
      - SSE generators compare their last-sent version against the current
        version to decide whether new data is available without iterating
        every ticker.

    Thread safety:
      - _lock guards _data and _version for synchronous callers (ingestion
        threads, background jobs).
      - _event (asyncio.Event) is set on every write so async SSE generators
        can await it without polling.
    """

    def __init__(self) -> None:
        self._data:    dict[str, PriceUpdate] = {}
        self._version: int = 0
        self._lock = threading.Lock()
        # Each asyncio event loop needs its own Event; we create one lazily.
        self._event: asyncio.Event | None = None

    # ------------------------------------------------------------------
    # Write path (called from ingestion thread or async task)
    # ------------------------------------------------------------------

    def update(self, update: PriceUpdate) -> int:
        """
        Store update and bump the version counter.
        Returns the new version number.
        """
        with self._lock:
            self._data[update.ticker] = update
            self._version += 1
            version = self._version
        self._notify()
        return version

    def update_many(self, updates: list[PriceUpdate]) -> int:
        """Batch-write a list of updates; increments version once per call."""
        with self._lock:
            for u in updates:
                self._data[u.ticker] = u
            self._version += 1
            version = self._version
        self._notify()
        return version

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def get(self, ticker: str) -> PriceUpdate | None:
        with self._lock:
            return self._data.get(ticker)

    def get_all(self) -> dict[str, PriceUpdate]:
        """Snapshot of all current prices (shallow copy — values are immutable)."""
        with self._lock:
            return dict(self._data)

    def iter_since(self, since_version: int) -> Iterator[PriceUpdate]:
        """
        Yield all updates whose ticker was written after `since_version`.

        Note: we don't store per-ticker write versions, so this conservatively
        yields every ticker currently in the cache when the global version is
        higher than `since_version`. For a watchlist of ≤20 symbols this is
        fine; a production system would keep per-ticker versions.
        """
        with self._lock:
            if self._version > since_version:
                yield from self._data.values()

    # ------------------------------------------------------------------
    # Async notification (SSE generators await this)
    # ------------------------------------------------------------------

    def _get_event(self) -> asyncio.Event:
        if self._event is None:
            self._event = asyncio.Event()
        return self._event

    def _notify(self) -> None:
        """Set the asyncio Event (safe to call from a sync thread)."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.call_soon_threadsafe(self._get_event().set)
        except RuntimeError:
            pass  # no event loop (e.g., during unit tests)

    async def wait_for_update(self, timeout: float = 30.0) -> bool:
        """
        Async-wait until the cache is written to (or timeout elapses).
        Returns True if an update arrived, False if timed out.
        Called by SSE generators between polls.
        """
        event = self._get_event()
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            event.clear()
            return True
        except asyncio.TimeoutError:
            return False
```

### Version counter design rationale

A single monotonic counter is simpler and cheaper than a per-symbol timestamp map. An SSE generator stores the version it last emitted; on wake-up it calls `iter_since(last_version)` and re-emits everything. For a watchlist of 5–15 symbols this is negligible. If the watchlist grew to thousands of symbols, we'd switch to per-symbol versions and a delta queue.

---

## 4. MarketDataSource — Abstract Interface

`MarketDataSource` is a thin rename of `MarketDataProvider` (defined in `market_interface.py`) documented here for completeness. It adds one method used by the live streaming path.

```python
# backend/app/services/data_ingestion/market_interface.py  (existing + extension)

class MarketDataSource(MarketDataProvider):
    """
    Extended abstract base used by the SSE streaming path.
    Adds get_price_updates() for push-style intraday refresh.
    """

    def get_price_updates(self, tickers: list[str]) -> list[PriceUpdate]:
        """
        Return the most recent PriceUpdate for each ticker.

        Default implementation: calls get_snapshot() + get_latest_quote()
        and merges the results. Override in subclasses for efficiency.
        """
        from .price_update import price_update_from_bar, price_update_from_quote
        snaps  = self.get_snapshot(tickers)
        quotes = self.get_latest_quote(tickers)
        updates = []
        for ticker in tickers:
            if ticker in quotes and ticker in snaps:
                u = price_update_from_quote(
                    quotes[ticker],
                    last_price=snaps[ticker].close,
                    volume=snaps[ticker].volume,
                )
            elif ticker in snaps:
                u = price_update_from_bar(snaps[ticker])
            else:
                continue
            updates.append(u)
        return updates
```

---

## 5. GBM Simulator — Correlated Moves and Random Events

The base `MarketSimulator` (see `MARKET_SIMULATOR.md`) generates independent GBM paths. The enhanced version below adds:

1. **Cross-ticker correlation** via a Cholesky-decomposed covariance matrix.
2. **Random events** (earnings surprises, flash crashes, macro shocks) that inject correlated jumps.

```python
# backend/app/services/data_ingestion/market_simulator.py  (additions)
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
from datetime import date

# Correlation matrix for the default watchlist
# Order: AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA, SPY, QQQ, BRK.B
_CORR = np.array([
    # AAPL  MSFT  NVDA  GOOGL AMZN  META  TSLA  SPY   QQQ   BRK.B
    [1.00, 0.82, 0.65, 0.78, 0.72, 0.70, 0.55, 0.80, 0.82, 0.60],  # AAPL
    [0.82, 1.00, 0.68, 0.85, 0.75, 0.73, 0.52, 0.82, 0.86, 0.62],  # MSFT
    [0.65, 0.68, 1.00, 0.62, 0.60, 0.65, 0.58, 0.70, 0.74, 0.48],  # NVDA
    [0.78, 0.85, 0.62, 1.00, 0.80, 0.75, 0.50, 0.80, 0.85, 0.60],  # GOOGL
    [0.72, 0.75, 0.60, 0.80, 1.00, 0.70, 0.52, 0.78, 0.80, 0.58],  # AMZN
    [0.70, 0.73, 0.65, 0.75, 0.70, 1.00, 0.55, 0.72, 0.76, 0.52],  # META
    [0.55, 0.52, 0.58, 0.50, 0.52, 0.55, 1.00, 0.58, 0.60, 0.38],  # TSLA
    [0.80, 0.82, 0.70, 0.80, 0.78, 0.72, 0.58, 1.00, 0.96, 0.72],  # SPY
    [0.82, 0.86, 0.74, 0.85, 0.80, 0.76, 0.60, 0.96, 1.00, 0.68],  # QQQ
    [0.60, 0.62, 0.48, 0.60, 0.58, 0.52, 0.38, 0.72, 0.68, 1.00],  # BRK.B
])

_WATCHLIST_ORDER = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
                    "META", "TSLA", "SPY", "QQQ", "BRK.B"]


@dataclass
class RandomEvent:
    """A synthetic market event that injects a correlated price jump."""
    date:         date
    event_type:   str            # "earnings_beat", "earnings_miss", "macro_shock", "flash_crash"
    affected:     list[str]      # tickers affected
    magnitude:    float          # signed return shock, e.g. 0.08 = +8%
    correlation:  float          # how strongly non-targeted tickers move with affected (0–1)


class CorrelatedMarketSimulator:
    """
    Extended simulator that generates cross-ticker correlated GBM paths
    and injects random events.

    Designed for backtesting scenarios where co-movement matters
    (e.g., testing risk-parity position sizing).
    """

    # Approximate annualised volatilities for the default watchlist
    _SIGMAS = {
        "AAPL": 0.22, "MSFT": 0.21, "NVDA": 0.40, "GOOGL": 0.22,
        "AMZN": 0.26, "META": 0.29, "TSLA": 0.48, "SPY": 0.13,
        "QQQ":  0.16, "BRK.B": 0.14,
    }
    _MUS = {t: 0.08 / 252 for t in _WATCHLIST_ORDER}   # 8% annualised drift / 252

    def __init__(self, seed: int = 42, event_prob: float = 0.002) -> None:
        """
        Args:
            seed: random seed for reproducibility.
            event_prob: probability of a random event on any given day (default 0.2%).
        """
        self._seed       = seed
        self._event_prob = event_prob
        self._chol       = np.linalg.cholesky(_CORR)   # lower-triangular Cholesky factor

    def generate_paths(
        self,
        tickers: list[str],
        from_date: date,
        to_date: date,
    ) -> dict[str, pd.DataFrame]:
        """
        Generate correlated OHLCV DataFrames for each ticker.
        Returns the same schema as MarketSimulator.get_bars().
        """
        tickers = [t for t in tickers if t in _WATCHLIST_ORDER]
        if not tickers:
            from .market_simulator import MarketSimulator
            sim = MarketSimulator(seed=self._seed)
            return {t: sim.get_bars(t, from_date, to_date) for t in tickers}

        bdays = pd.bdate_range(from_date, to_date)
        n     = len(bdays)
        rng   = np.random.default_rng(self._seed)

        # Build index mapping for subset of tickers
        idxs    = [_WATCHLIST_ORDER.index(t) for t in tickers]
        sigmas  = np.array([self._SIGMAS[t] / np.sqrt(252) for t in tickers])
        mus     = np.array([self._MUS[t] for t in tickers])
        chol_sub = self._chol[np.ix_(idxs, idxs)]

        # Correlated standard normals: Z = L @ eps where eps ~ N(0, I)
        eps  = rng.standard_normal((len(tickers), n))
        Z    = chol_sub @ eps                            # (n_tickers, n_days)

        # GBM log-returns
        log_ret = (mus - 0.5 * sigmas**2)[:, None] + sigmas[:, None] * Z

        # Inject random events
        log_ret = self._inject_events(log_ret, tickers, bdays, rng)

        results = {}
        for i, ticker in enumerate(tickers):
            from .market_simulator import _params_for
            p = _params_for(ticker)
            closes = p.start_price * np.exp(np.cumsum(log_ret[i]))
            intra_sigma = sigmas[i] * 0.7
            daily_range = np.abs(rng.normal(0, intra_sigma, n)) * closes
            opens  = closes * np.exp(rng.normal(0, sigmas[i] * 0.3, n))
            highs  = np.maximum(opens, closes) + daily_range * rng.uniform(0.2, 0.8, n)
            lows   = np.minimum(opens, closes) - daily_range * rng.uniform(0.2, 0.8, n)
            lows   = np.maximum(lows, 0.01)
            volume = rng.lognormal(np.log(5_000_000), 0.5, n).astype(int)
            results[ticker] = pd.DataFrame({
                "date":   pd.DatetimeIndex(bdays).tz_localize("America/New_York"),
                "open":   np.round(opens, 4),
                "high":   np.round(highs, 4),
                "low":    np.round(lows, 4),
                "close":  np.round(closes, 4),
                "volume": volume,
                "vwap":   np.round((opens + highs + lows + closes) / 4, 4),
            })
        return results

    def _inject_events(
        self,
        log_ret:  np.ndarray,   # (n_tickers, n_days)
        tickers:  list[str],
        bdays,
        rng: np.random.Generator,
    ) -> np.ndarray:
        """
        Inject random events into the log-return matrix.

        Events are rare (default 0.2%/day) and affect one primary ticker
        with correlated spillover to others (70–90% of the primary shock
        scaled by the correlation to that ticker).
        """
        n_days = log_ret.shape[1]
        for day_idx in range(n_days):
            if rng.random() > self._event_prob:
                continue
            # Pick a primary ticker at random
            primary_idx = int(rng.integers(len(tickers)))
            primary     = tickers[primary_idx]
            event_type  = rng.choice(["earnings_beat", "earnings_miss", "macro_shock"])
            magnitude   = {
                "earnings_beat":  rng.uniform(0.04, 0.12),
                "earnings_miss":  -rng.uniform(0.04, 0.15),
                "macro_shock":    rng.choice([-1, 1]) * rng.uniform(0.02, 0.06),
            }[event_type]
            log_ret[primary_idx, day_idx] += magnitude
            # Correlated spillover — scaled by correlation matrix entries
            for j, ticker in enumerate(tickers):
                if j == primary_idx:
                    continue
                corr = _CORR[
                    _WATCHLIST_ORDER.index(ticker),
                    _WATCHLIST_ORDER.index(primary),
                ]
                log_ret[j, day_idx] += magnitude * corr * rng.uniform(0.5, 0.9)
        return log_ret
```

---

## 6. Massive API Client — Lazy Imports and Error Resilience

The `MassiveProvider` (see `MARKET_INTERFACE.md`) uses lazy imports and exponential-backoff retry. This section documents the retry pattern in detail and adds tenacity-based wrapping.

```python
# backend/app/services/data_ingestion/massive_provider.py  (retry additions)
from __future__ import annotations

import os
import time
import logging

import requests

log = logging.getLogger(__name__)


def _make_session() -> requests.Session:
    """Lazy — only imported/created when MassiveProvider is instantiated."""
    s = requests.Session()
    s.headers.update({"Accept": "application/json"})
    return s


class _RetryingSession:
    """
    Wraps requests.Session with exponential backoff on 429 and transient errors.

    Designed so unit tests can replace ._session with a mock without importing
    the real requests library at module load time.
    """

    MAX_ATTEMPTS = 5
    RETRY_ON = {429, 500, 502, 503, 504}

    def __init__(self) -> None:
        self._session: requests.Session | None = None   # lazy

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = _make_session()
        return self._session

    def get(self, url: str, params: dict, timeout: float = 15) -> dict:
        for attempt in range(self.MAX_ATTEMPTS):
            try:
                r = self._get_session().get(url, params=params, timeout=timeout)
            except requests.ConnectionError as exc:
                log.warning("Massive API connection error (attempt %d): %s", attempt + 1, exc)
                time.sleep(2 ** attempt)
                continue

            if r.status_code in self.RETRY_ON:
                backoff = min(2 ** attempt, 60)
                log.warning(
                    "Massive API HTTP %s (attempt %d/%d); sleeping %ds",
                    r.status_code, attempt + 1, self.MAX_ATTEMPTS, backoff,
                )
                time.sleep(backoff)
                continue

            r.raise_for_status()
            body = r.json()
            if body.get("status") == "ERROR":
                raise RuntimeError(f"Massive API error: {body.get('error')}")
            return body

        raise RuntimeError(
            f"Massive API unreachable after {self.MAX_ATTEMPTS} attempts: {url}"
        )
```

### Lazy import pattern for optional dependency

`MassiveProvider` is only instantiated when `MASSIVE_API_KEY` is set, so the `requests` library is imported inside the module rather than at the top of `market_interface.py`. This keeps unit-test imports clean (tests never set the key and never trigger the import).

```python
def create_provider(db_session=None):
    key = os.environ.get("MASSIVE_API_KEY")
    if key:
        from .massive_provider import MassiveProvider   # lazy — only when key present
        return MassiveProvider(api_key=key)
    from .simulator_provider import SimulatorProvider
    return SimulatorProvider(db_session=db_session)
```

---

## 7. SSE Streaming Endpoint — Disconnect Detection

The `GET /stream/prices` endpoint streams `PriceUpdate` events to the React dashboard via Server-Sent Events. Each event is a JSON object; the frontend uses the native `EventSource` API.

```python
# backend/app/api/stream.py
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.dependencies import get_price_cache, get_watchlist
from app.services.data_ingestion.price_cache import PriceCache

router = APIRouter()
log    = logging.getLogger(__name__)


async def _sse_generator(
    request:   Request,
    cache:     PriceCache,
    tickers:   list[str],
    since_ver: int,
) -> AsyncIterator[str]:
    """
    Yields SSE-formatted strings until the client disconnects.

    Protocol:
      - On first connect, immediately emit the current snapshot for all
        requested tickers (so the UI is never empty).
      - Then wait for cache updates; emit only when version advances.
      - Send a keepalive comment (:) every 25 seconds to prevent proxy
        timeouts.
    """
    # Initial snapshot
    snapshot = cache.get_all()
    for ticker in tickers:
        if ticker in snapshot:
            payload = json.dumps(snapshot[ticker].to_sse_dict())
            yield f"event: price\ndata: {payload}\n\n"
    last_version = cache.version

    while True:
        # Disconnect detection: check if the client closed the connection
        if await request.is_disconnected():
            log.info("SSE client disconnected; closing generator")
            break

        # Wait up to 25 s for a new cache write (keepalive timeout)
        updated = await cache.wait_for_update(timeout=25.0)

        if not updated:
            # Keepalive: SSE comment — keeps the connection alive through proxies
            yield ": keepalive\n\n"
            continue

        # Emit all updates since the last version we sent
        for update in cache.iter_since(last_version):
            if update.ticker in tickers:
                payload = json.dumps(update.to_sse_dict())
                yield f"event: price\ndata: {payload}\n\n"
        last_version = cache.version


@router.get("/stream/prices")
async def stream_prices(
    request:  Request,
    tickers:  list[str] = Query(default=[]),
    since:    int        = Query(default=0, description="Cache version to stream from"),
    cache:    PriceCache  = Depends(get_price_cache),
    watchlist: list[str] = Depends(get_watchlist),
) -> StreamingResponse:
    """
    SSE endpoint. Streams PriceUpdate events for the requested tickers.

    If `tickers` is empty, streams the full watchlist.
    The `since` parameter enables reconnect without re-sending stale data
    (pass the last received version number).

    Frontend usage:
        const es = new EventSource('/stream/prices?tickers=AAPL&tickers=MSFT');
        es.addEventListener('price', e => setPrice(JSON.parse(e.data)));
    """
    requested = tickers if tickers else watchlist
    # Validate against watchlist — never stream tickers we don't track
    valid = [t for t in requested if t in watchlist]

    return StreamingResponse(
        _sse_generator(request, cache, valid, since),
        media_type="text/event-stream",
        headers={
            "Cache-Control":  "no-cache",
            "X-Accel-Buffering": "no",   # disable Nginx buffering
            "Connection":     "keep-alive",
        },
    )
```

### Disconnect detection — two mechanisms

1. **`request.is_disconnected()`** — Starlette's built-in async check; polling this in the loop is the recommended FastAPI pattern for SSE disconnect detection.
2. **`wait_for_update(timeout=25)`** — if the client disconnects while we're waiting, the `asyncio.CancelledError` propagates and the generator stops automatically.

The generator never raises; it simply stops yielding. FastAPI cleans up the `StreamingResponse` automatically.

---

## 8. FastAPI Lifecycle Integration and Dependency Injection

### Lifespan (startup/shutdown)

```python
# backend/app/main.py
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import settings
from app.services.data_ingestion.market_interface import create_provider
from app.services.data_ingestion.price_cache import PriceCache

log = logging.getLogger(__name__)

# Module-level singletons — injected into routes via Depends()
_price_cache:   PriceCache | None = None
_watchlist:     list[str]  = []
_refresh_task:  asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: initialise the cache, load the watchlist, start the background
    price-refresh task.
    Shutdown: cancel the refresh task cleanly.
    """
    global _price_cache, _watchlist, _refresh_task

    _watchlist   = settings.watchlist        # list from env / DB
    _price_cache = PriceCache()

    provider = create_provider()             # MassiveProvider or SimulatorProvider

    # Seed the cache immediately so the first SSE connect gets data
    try:
        updates = provider.get_price_updates(_watchlist)
        _price_cache.update_many(updates)
        log.info("PriceCache seeded with %d tickers", len(updates))
    except Exception:
        log.warning("Initial price seed failed; cache starts empty", exc_info=True)

    _refresh_task = asyncio.create_task(
        _price_refresh_loop(provider, _price_cache, _watchlist),
        name="price_refresh",
    )

    yield   # application runs here

    # Shutdown
    if _refresh_task:
        _refresh_task.cancel()
        try:
            await _refresh_task
        except asyncio.CancelledError:
            pass
    log.info("Price refresh task stopped")


app = FastAPI(title="AI Trading Workstation", lifespan=lifespan)


async def _price_refresh_loop(provider, cache: PriceCache, tickers: list[str]) -> None:
    """
    Background task: poll the provider every PRICE_REFRESH_INTERVAL seconds
    and update the cache. SSE generators wake up automatically via the Event.
    """
    interval = settings.price_refresh_interval   # default 60 s (env: PRICE_REFRESH_INTERVAL)
    while True:
        await asyncio.sleep(interval)
        try:
            updates = await asyncio.to_thread(provider.get_price_updates, tickers)
            cache.update_many(updates)
            log.debug("PriceCache refreshed: %d tickers, version %d", len(updates), cache.version)
        except Exception:
            log.warning("Price refresh failed", exc_info=True)
```

### Dependency injection

```python
# backend/app/dependencies.py
from __future__ import annotations

from fastapi import HTTPException

import app.main as _main


def get_price_cache():
    """FastAPI dependency: returns the shared PriceCache singleton."""
    if _main._price_cache is None:
        raise HTTPException(503, detail="Price cache not yet initialised")
    return _main._price_cache


def get_watchlist() -> list[str]:
    """FastAPI dependency: returns the current watchlist."""
    return _main._watchlist
```

### Using dependencies in a REST endpoint

```python
# backend/app/api/prices.py
from fastapi import APIRouter, Depends
from app.dependencies import get_price_cache, get_watchlist
from app.services.data_ingestion.price_cache import PriceCache

router = APIRouter()

@router.get("/prices/snapshot")
def get_snapshot(
    cache:     PriceCache  = Depends(get_price_cache),
    watchlist: list[str]   = Depends(get_watchlist),
):
    """Return the latest price for every watchlist symbol."""
    all_prices = cache.get_all()
    return {t: all_prices[t].to_sse_dict() for t in watchlist if t in all_prices}

@router.get("/prices/{ticker}")
def get_price(
    ticker: str,
    cache:  PriceCache = Depends(get_price_cache),
    watchlist: list[str] = Depends(get_watchlist),
):
    if ticker not in watchlist:
        from fastapi import HTTPException
        raise HTTPException(404, detail=f"{ticker} not on watchlist")
    update = cache.get(ticker)
    if update is None:
        from fastapi import HTTPException
        raise HTTPException(503, detail="Price not yet available")
    return update.to_sse_dict()
```

---

## 9. Watchlist Coordination Flow

The watchlist is the list of symbols that drive everything: ingestion, feature computation, signal generation, and SSE streaming.

### Source of truth

```
Priority (highest first):
  1. WATCHLIST env var (comma-separated): "AAPL,MSFT,NVDA,SPY,QQQ"
  2. instruments table (is_active = true)
  3. Hardcoded default (fallback for CI/tests): ["AAPL","MSFT","NVDA","SPY","QQQ"]
```

```python
# backend/app/core/config.py  (watchlist resolution)
from __future__ import annotations

import os
from functools import lru_cache

_DEFAULT_WATCHLIST = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
                      "META", "TSLA", "SPY", "QQQ", "BRK.B"]


class Settings:
    watchlist: list[str]
    price_refresh_interval: int

    def __init__(self) -> None:
        raw = os.environ.get("WATCHLIST", "")
        self.watchlist = [t.strip() for t in raw.split(",") if t.strip()] or _DEFAULT_WATCHLIST
        self.price_refresh_interval = int(os.environ.get("PRICE_REFRESH_INTERVAL", "60"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
```

### End-to-end coordination sequence

```
Startup (lifespan):
  1. load_watchlist()                    → ["AAPL", "MSFT", ...]
  2. create_provider()                   → MassiveProvider | SimulatorProvider
  3. provider.get_price_updates(watchlist) → [PriceUpdate, ...]
  4. cache.update_many(updates)          → version = 1
  5. asyncio.create_task(refresh_loop)

Every PRICE_REFRESH_INTERVAL seconds (refresh_loop):
  1. provider.get_price_updates(watchlist) → [PriceUpdate, ...]
  2. cache.update_many(updates)          → version += 1
  3. cache._notify()                     → asyncio.Event.set()

Every SSE client (_sse_generator):
  1. await cache.wait_for_update()       ← blocks here
  2. [Event fires]
  3. for update in cache.iter_since(last_version): yield SSE event
  4. last_version = cache.version
  5. goto 1

Watchlist change (Settings page PUT /watchlist):
  1. Validate new symbols
  2. Update instruments.is_active in DB
  3. settings.watchlist = new_list       (or restart required if using lru_cache)
  4. Next refresh_loop iteration picks up new symbols automatically
```

### Interaction diagram

```
React dashboard              FastAPI                   PriceCache          Provider
      │                         │                          │                   │
      │── GET /stream/prices ──►│                          │                   │
      │                         │── get_all() ────────────►│                   │
      │◄── SSE: initial snap ───│                          │                   │
      │                         │                          │                   │
      │                    [refresh_loop wakes]            │                   │
      │                         │── get_price_updates() ──────────────────────►│
      │                         │◄─ [PriceUpdate list] ───────────────────────│
      │                         │── update_many() ────────►│                   │
      │                         │                          │── Event.set() ──► │
      │                         │                          │                   │
      │                    [_sse_generator wakes]          │                   │
      │                         │── iter_since(v) ─────────►│                  │
      │◄── SSE: price event ────│                          │                   │
      │                         │                          │                   │
```

---

## 10. Full Test Suite

### 10.1 PriceUpdate

```python
# tests/backend/test_price_update.py
import pytest
from datetime import datetime, timezone
from app.services.data_ingestion.price_update import PriceUpdate, price_update_from_bar
from app.services.data_ingestion.market_interface import Bar
from datetime import date


def _make_update(**kwargs) -> PriceUpdate:
    defaults = dict(
        ticker="AAPL", price=185.0, bid=184.95, ask=185.05,
        volume=50_000_000, timestamp=datetime(2024, 1, 15, 20, 0, 0, tzinfo=timezone.utc),
    )
    return PriceUpdate(**{**defaults, **kwargs})


def test_immutable():
    u = _make_update()
    with pytest.raises(Exception):   # frozen dataclass raises FrozenInstanceError
        u.price = 200.0


def test_mid_with_bid_ask():
    u = _make_update(bid=184.90, ask=185.10)
    assert u.mid == pytest.approx(185.00, abs=1e-6)


def test_mid_without_bid_ask():
    u = _make_update(bid=None, ask=None)
    assert u.mid == u.price


def test_spread():
    u = _make_update(bid=184.90, ask=185.10)
    assert u.spread == pytest.approx(0.20, abs=1e-6)


def test_spread_none_when_no_quote():
    u = _make_update(bid=None, ask=None)
    assert u.spread is None


def test_to_sse_dict_keys():
    u = _make_update()
    d = u.to_sse_dict()
    assert set(d.keys()) == {"ticker", "price", "bid", "ask", "mid", "spread", "volume", "timestamp"}


def test_from_bar():
    bar = Bar(ticker="MSFT", date=date(2024, 1, 15), open=374.0, high=378.0,
              low=373.0, close=376.5, volume=22_000_000, vwap=375.8)
    u = price_update_from_bar(bar)
    assert u.ticker == "MSFT"
    assert u.price  == 376.5
    assert u.bid    is None
    assert u.ask    is None
```

### 10.2 PriceCache

```python
# tests/backend/test_price_cache.py
import asyncio
import threading
import time
from datetime import datetime, timezone

import pytest

from app.services.data_ingestion.price_cache import PriceCache
from app.services.data_ingestion.price_update import PriceUpdate


def _u(ticker: str, price: float) -> PriceUpdate:
    return PriceUpdate(
        ticker=ticker, price=price, bid=None, ask=None,
        volume=0, timestamp=datetime(2024, 1, 15, 20, 0, tzinfo=timezone.utc),
    )


def test_update_increments_version():
    cache = PriceCache()
    assert cache.version == 0
    cache.update(_u("AAPL", 185.0))
    assert cache.version == 1
    cache.update(_u("MSFT", 375.0))
    assert cache.version == 2


def test_get_returns_latest():
    cache = PriceCache()
    cache.update(_u("AAPL", 180.0))
    cache.update(_u("AAPL", 185.0))
    assert cache.get("AAPL").price == 185.0


def test_get_returns_none_for_unknown():
    cache = PriceCache()
    assert cache.get("UNKNOWN") is None


def test_update_many_single_version_bump():
    cache = PriceCache()
    cache.update_many([_u("AAPL", 185.0), _u("MSFT", 375.0)])
    assert cache.version == 1


def test_get_all_snapshot():
    cache = PriceCache()
    cache.update_many([_u("AAPL", 185.0), _u("MSFT", 375.0)])
    snap = cache.get_all()
    assert set(snap.keys()) == {"AAPL", "MSFT"}


def test_iter_since_yields_all_when_version_advanced():
    cache = PriceCache()
    cache.update_many([_u("AAPL", 185.0), _u("MSFT", 375.0)])
    results = list(cache.iter_since(0))
    assert len(results) == 2


def test_iter_since_yields_nothing_when_current():
    cache = PriceCache()
    cache.update(_u("AAPL", 185.0))
    results = list(cache.iter_since(cache.version))
    assert results == []


def test_thread_safety():
    """Multiple threads writing concurrently must not corrupt the version counter."""
    cache = PriceCache()
    n_threads, n_writes = 10, 100

    def writer(ticker: str):
        for i in range(n_writes):
            cache.update(_u(ticker, float(i)))

    threads = [threading.Thread(target=writer, args=(f"T{i}",)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert cache.version == n_threads * n_writes


@pytest.mark.asyncio
async def test_wait_for_update_resolves_on_write():
    cache = PriceCache()

    async def write_after_delay():
        await asyncio.sleep(0.05)
        cache.update(_u("AAPL", 185.0))

    asyncio.create_task(write_after_delay())
    updated = await cache.wait_for_update(timeout=1.0)
    assert updated is True


@pytest.mark.asyncio
async def test_wait_for_update_times_out():
    cache = PriceCache()
    updated = await cache.wait_for_update(timeout=0.05)
    assert updated is False
```

### 10.3 Market Interface (provider selection)

```python
# tests/backend/test_market_interface.py
import pytest
from app.services.data_ingestion.market_interface import create_provider


def test_returns_simulator_without_key(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    from app.services.data_ingestion.simulator_provider import SimulatorProvider
    assert isinstance(create_provider(), SimulatorProvider)


def test_returns_massive_with_key(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "fake_key_abc123")
    from app.services.data_ingestion.massive_provider import MassiveProvider
    assert isinstance(create_provider(), MassiveProvider)
```

### 10.4 Market Simulator (GBM invariants)

```python
# tests/backend/test_market_simulator.py
import pandas as pd
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


def test_unknown_ticker_fallback():
    df = SIM.get_bars("XYZFAKE", date(2023, 1, 1), date(2023, 3, 31))
    assert len(df) > 0


def test_latest_bar_returns_bar():
    from app.services.data_ingestion.market_interface import Bar
    bar = SIM.latest_bar("AAPL")
    assert isinstance(bar, Bar)
    assert bar.close > 0


def test_latest_quote_spread():
    quote = SIM.latest_quote("AAPL")
    assert quote.ask > quote.bid
    assert quote.bid > 0
```

### 10.5 Correlated Simulator

```python
# tests/backend/test_correlated_simulator.py
import numpy as np
import pytest
from datetime import date
from app.services.data_ingestion.market_simulator import CorrelatedMarketSimulator


SIM = CorrelatedMarketSimulator(seed=42, event_prob=0.0)  # no events for invariant tests


def test_returns_all_requested_tickers():
    tickers = ["AAPL", "MSFT", "SPY"]
    paths = SIM.generate_paths(tickers, date(2023, 1, 1), date(2023, 6, 30))
    assert set(paths.keys()) == set(tickers)


def test_ohlc_invariants():
    paths = SIM.generate_paths(["AAPL", "MSFT"], date(2023, 1, 1), date(2023, 3, 31))
    for ticker, df in paths.items():
        assert (df["high"] >= df["close"]).all(), f"{ticker}: high < close"
        assert (df["low"]  <= df["close"]).all(), f"{ticker}: low > close"
        assert (df["close"] > 0).all(), f"{ticker}: negative close"


def test_correlated_paths_are_correlated():
    """SPY and QQQ should have high return correlation (>0.8 on average)."""
    paths = SIM.generate_paths(["SPY", "QQQ"], date(2020, 1, 2), date(2022, 12, 31))
    spy_ret = paths["SPY"]["close"].pct_change().dropna()
    qqq_ret = paths["QQQ"]["close"].pct_change().dropna()
    corr = spy_ret.corr(qqq_ret)
    assert corr > 0.80, f"SPY/QQQ simulated correlation too low: {corr:.3f}"


def test_events_inject_jumps():
    """With high event probability, variance should be higher than with none."""
    sim_events = CorrelatedMarketSimulator(seed=42, event_prob=0.1)
    sim_none   = CorrelatedMarketSimulator(seed=42, event_prob=0.0)
    tickers    = ["AAPL"]
    drange     = (date(2022, 1, 1), date(2022, 12, 31))
    var_events = sim_events.generate_paths(tickers, *drange)["AAPL"]["close"].std()
    var_none   = sim_none.generate_paths(tickers, *drange)["AAPL"]["close"].std()
    assert var_events > var_none
```

### 10.6 SSE Endpoint

```python
# tests/backend/test_sse_endpoint.py
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.data_ingestion.price_update import PriceUpdate
from app.services.data_ingestion.price_cache import PriceCache


def _seed_cache(cache: PriceCache, tickers: list[str]) -> None:
    for ticker in tickers:
        cache.update(PriceUpdate(
            ticker=ticker, price=100.0, bid=99.9, ask=100.1,
            volume=1_000_000, timestamp=datetime(2024, 1, 15, 20, 0, tzinfo=timezone.utc),
        ))


@pytest.fixture
def client_with_cache():
    import app.main as _main
    cache = PriceCache()
    _seed_cache(cache, ["AAPL", "MSFT"])
    _main._price_cache = cache
    _main._watchlist   = ["AAPL", "MSFT"]
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    _main._price_cache = None
    _main._watchlist   = []


def test_sse_returns_initial_snapshot(client_with_cache):
    """SSE stream should immediately emit the seeded prices on connect."""
    response = client_with_cache.get(
        "/stream/prices?tickers=AAPL",
        headers={"Accept": "text/event-stream"},
        stream=True,
        timeout=2,
    )
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]

    # Read first event
    content = b""
    for chunk in response.iter_content(chunk_size=None):
        content += chunk
        if b"\n\n" in content:
            break

    event_str = content.decode()
    assert "event: price" in event_str
    data_line = next(l for l in event_str.splitlines() if l.startswith("data:"))
    payload   = json.loads(data_line[len("data:"):].strip())
    assert payload["ticker"] == "AAPL"
    assert payload["price"]  == pytest.approx(100.0)


def test_sse_rejects_ticker_not_on_watchlist(client_with_cache):
    """Tickers outside the watchlist should not appear in the stream."""
    response = client_with_cache.get(
        "/stream/prices?tickers=TSLA",
        headers={"Accept": "text/event-stream"},
        stream=True,
        timeout=1,
    )
    # TSLA not in watchlist → stream is empty (no events emitted)
    content = b""
    try:
        for chunk in response.iter_content(chunk_size=None):
            content += chunk
            if len(content) > 10:
                break
    except Exception:
        pass
    # No price events for TSLA
    assert b"TSLA" not in content
```

### 10.7 MassiveProvider retry logic

```python
# tests/backend/test_massive_provider.py
import pytest
from unittest.mock import MagicMock, call, patch
from requests.exceptions import ConnectionError as ReqConnError


def _make_provider(key: str = "test_key"):
    import os
    os.environ["MASSIVE_API_KEY"] = key
    from app.services.data_ingestion.massive_provider import MassiveProvider
    return MassiveProvider(api_key=key)


def test_retry_on_429(monkeypatch):
    """Provider should retry up to MAX_ATTEMPTS on 429 responses."""
    provider = _make_provider()

    responses = []
    for _ in range(4):
        r = MagicMock()
        r.status_code = 429
        responses.append(r)
    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.json.return_value = {"status": "OK", "results": []}
    responses.append(ok_resp)

    session_mock = MagicMock()
    session_mock.get.side_effect = responses
    provider._session = session_mock    # inject mock session into _RetryingSession

    with patch("time.sleep"):           # don't actually sleep in tests
        result = provider._get("http://fake", {})
    assert result == {"status": "OK", "results": []}
    assert session_mock.get.call_count == 5


def test_raises_after_max_retries(monkeypatch):
    provider = _make_provider()

    r = MagicMock()
    r.status_code = 429
    session_mock  = MagicMock()
    session_mock.get.return_value = r
    provider._session = session_mock

    with patch("time.sleep"), pytest.raises(RuntimeError, match="unreachable"):
        provider._get("http://fake", {})


def test_raises_on_api_error_status(monkeypatch):
    provider = _make_provider()
    ok_resp  = MagicMock()
    ok_resp.status_code = 200
    ok_resp.json.return_value = {"status": "ERROR", "error": "Unknown ticker"}
    session_mock = MagicMock()
    session_mock.get.return_value = ok_resp
    provider._session = session_mock

    with pytest.raises(RuntimeError, match="Massive API error"):
        provider._get("http://fake", {})
```

---

## 11. Environment Variable Reference

Add all of the following to `.env.example`:

```
# Market data provider selection
# Leave blank to use the SimulatorProvider (no API key needed for local dev/CI)
MASSIVE_API_KEY=

# Optional: override base URL (useful for local proxy / mock server)
MASSIVE_BASE_URL=https://api.polygon.io

# Watchlist: comma-separated ticker symbols
WATCHLIST=AAPL,MSFT,NVDA,GOOGL,AMZN,META,TSLA,SPY,QQQ,BRK.B

# How often (seconds) the background task refreshes prices in the cache
PRICE_REFRESH_INTERVAL=60
```

---

## 12. File Checklist

When the subsystem is fully implemented, these files must exist:

```
backend/app/services/data_ingestion/
├── __init__.py
├── market_interface.py          # Bar, Quote, MarketDataProvider ABC, create_provider()
├── massive_provider.py          # MassiveProvider + _RetryingSession
├── simulator_provider.py        # SimulatorProvider wrapping MarketSimulator
├── market_simulator.py          # MarketSimulator + CorrelatedMarketSimulator
├── price_update.py              # PriceUpdate dataclass + constructors
└── price_cache.py               # PriceCache (thread-safe, version counter)

backend/app/
├── main.py                      # lifespan, _price_refresh_loop
├── dependencies.py              # get_price_cache(), get_watchlist()
└── api/
    ├── prices.py                # GET /prices/snapshot, GET /prices/{ticker}
    └── stream.py                # GET /stream/prices (SSE)

tests/backend/
├── test_price_update.py
├── test_price_cache.py
├── test_market_interface.py
├── test_market_simulator.py
├── test_correlated_simulator.py
├── test_sse_endpoint.py
└── test_massive_provider.py
```
