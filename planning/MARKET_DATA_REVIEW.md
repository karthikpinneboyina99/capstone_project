# Market Data Backend — Code Review

**Reviewed:** 2026-06-24  
**Reviewer:** Claude Code (Sonnet 4.6)  
**Scope:** All files under `backend/app/services/data_ingestion/`, `tests/backend/`, and planning docs in `planning/`

---

## 1. Test Results

```
115 passed, 0 failed  (with full dep set)
5 failed, 110 passed  (minimal venv — sqlalchemy missing)
16 warnings           (pd.Timestamp.utcnow deprecation)
```

The 5 failures in the minimal venv are not code bugs — they are an environment setup issue described in §4.1. All 115 tests pass once `sqlalchemy` is installed.

---

## 2. What Was Reviewed

| File | Role |
|---|---|
| `market_interface.py` | `Bar`, `Quote` dataclasses; `MarketDataProvider` ABC; `create_provider()` factory |
| `market_simulator.py` | `MarketSimulator` — DB replay + GBM synthetic mode |
| `simulator_provider.py` | Thin `MarketDataProvider` wrapper around `MarketSimulator` |
| `massive_provider.py` | Live Polygon/Massive REST API client with retry |
| `tests/backend/test_market_interface.py` | 14 tests: dataclass contracts + factory |
| `tests/backend/test_market_simulator.py` | 51 tests: schema, invariants, determinism, DB replay |
| `tests/backend/test_simulator_provider.py` | 27 tests: full provider interface |
| `tests/backend/test_massive_provider.py` | 23 tests: HTTP mocking, retry, pagination, auth |
| `planning/MARKET_INTERFACE.md` | Interface contract specification |
| `planning/MARKET_SIMULATOR.md` | Simulator design and guarantees |
| `planning/MASSIVE_API.md` | Polygon/Massive API reference |
| `planning/MARKET_DATA_DESIGN.md` | Full-stack design (SSE, PriceCache, lifecycle) |

---

## 3. Strengths

### 3.1 Architecture and Abstractions
The `MarketDataProvider` ABC is a well-designed seam. All callers — feature engineering, the backtester, and the live executor — will import from `market_interface.py` and never see the concrete provider. Switching from `SimulatorProvider` to `MassiveProvider` at runtime via `MASSIVE_API_KEY` is clean and tested. The lazy import of `MassiveProvider` inside `create_provider()` means the `requests` dependency is only pulled in when the key is present, keeping CI imports clean.

### 3.2 Data Model Correctness
`Bar` and `Quote` are `frozen=True` dataclasses — immutable, hashable, safe to share across threads without copying. This is the right choice for objects that flow through a cache into SSE generators (as documented in `MARKET_DATA_DESIGN.md`). The `vwap: float | None` field in `Bar` correctly models the reality that the simulator doesn't always have VWAP.

### 3.3 GBM Simulator Design
The synthetic mode uses the correct GBM formula (`S(t+1) = S(t)*exp((μ - σ²/2)dt + σ√dt·Z)`), per-ticker seeds derived from a deterministic hash so any ticker gets a reproducible path, and a price floor at $0.01. OHLC invariants (high ≥ open, high ≥ close, low ≤ open, low ≤ close) are enforced by construction, not asserted after the fact. The `^` XOR between per-ticker seed and global seed ensures different simulator instances produce independent paths for the same ticker.

### 3.4 HTTP Retry Logic
`MassiveProvider._get()` retries up to 5 times on 429 with exponential backoff (`2^attempt` seconds). It correctly handles the case where the Polygon response body has `status: "ERROR"` on an HTTP 200 — a known API footgun documented in `MASSIVE_API.md`. Pagination via `next_url` is handled cleanly in `_fetch_aggs`.

### 3.5 Test Quality
The test suite is thorough and well-organized:
- Schema tests verify exact column lists, not just "has columns"
- Invariant tests cover all six OHLC relationships independently
- Determinism is tested from both directions (same seed → same data; different seed → different data)
- DB replay mode uses a correctly-structured `MagicMock` and verifies that the ticker parameter is passed through to the SQL query
- HTTP mocking patches `requests.get` at module scope, making tests fast and offline
- The pagination test verifies multi-page data is correctly concatenated

---

## 4. Bugs and Correctness Issues

### 4.1 `TestDBReplayMode` fails without `sqlalchemy` installed — environment issue  
**Severity: Low (environment, not logic)**  
`_db_bars()` uses a lazy `from sqlalchemy import text` inside the method body. This means tests that inject a `MagicMock` session still trigger the real `sqlalchemy` import before the mock can intercept anything. In a minimal venv the 5 DB replay tests fail with `ModuleNotFoundError: No module named 'sqlalchemy'`.

The fix is to add `sqlalchemy` to the `pip install` step in the test/CI setup. The lazy import itself is fine as a pattern — it exists precisely to avoid importing sqlalchemy at module load time in cases where it isn't installed. The issue is that the test venv must still have it installed.

**Action:** Add `sqlalchemy` to the test dependency list (either `requirements.txt` dev extras or CI setup step). No code change needed.

---

### 4.2 `daily_summary` ignores the `as_of` date — correctness bug  
**Severity: High (will cause lookahead in backtester)**  
```python
# market_simulator.py:137-139
def daily_summary(self, as_of: date) -> dict[str, Bar]:
    tickers = list(_KNOWN.keys())
    return {t: self.latest_bar(t) for t in tickers}  # ← always today's bar
```
`latest_bar()` calls `get_bars(ticker, date.today() - timedelta(days=7), date.today())`. So `daily_summary(date(2021, 3, 15))` returns today's GBM bars, not bars as of 2021-03-15. When the backtesting engine calls this method to price positions on historical dates, it will receive current-day data — a form of lookahead bias.

**Fix:** Pass `as_of` through:
```python
def daily_summary(self, as_of: date) -> dict[str, Bar]:
    tickers = list(_KNOWN.keys())
    result = {}
    for t in tickers:
        df = self.get_bars(t, as_of - timedelta(days=1), as_of)
        if df.empty:
            p = _params_for(t).start_price
            result[t] = Bar(ticker=t, date=as_of, open=p, high=p, low=p, close=p,
                            volume=1_000_000, vwap=p)
        else:
            row = df.iloc[-1]
            result[t] = Bar(ticker=t, date=as_of, open=float(row["open"]),
                            high=float(row["high"]), low=float(row["low"]),
                            close=float(row["close"]), volume=int(row["volume"]),
                            vwap=row.get("vwap"))
    return result
```
A test should be added: call `daily_summary(date(2021, 1, 5))` and verify the returned bars have dates on or before 2021-01-05.

---

### 4.3 `pd.Timestamp.utcnow()` deprecation — 16 warnings  
**Severity: Low (future break, not current)**  
```python
# market_simulator.py:134
timestamp=pd.Timestamp.utcnow(),
```
`Timestamp.utcnow()` is deprecated in pandas 4+ and will be removed in a future release, producing 16 warnings across the test run. The `latest_quote` method in `MarketSimulator` is the only call site.

**Fix:**
```python
timestamp=pd.Timestamp.now("UTC"),
```

---

## 5. Code Quality Issues

### 5.1 Unused imports in `market_simulator.py`  
```python
from typing import Optional      # never referenced
from pandas.tseries.offsets import BDay  # never referenced (code uses pd.bdate_range)
```
Both can be deleted without affecting anything.

---

### 5.2 `MassiveProvider.get_snapshot` always uses `date.today()` for `Bar.date`  
```python
# massive_provider.py:69
date=date.today(),  # ← not the actual bar date from the snapshot
```
The Polygon snapshot response carries a timestamp (`updated`) but the code ignores it for the `date` field and uses today's date. This is documented implicitly (the comment "most recent EOD or intraday bar") but if the executor calls `get_snapshot` after market close on a day with stale data, the `Bar.date` will be misleading. Not a critical bug for paper trading, but worth noting.

---

### 5.3 Redundant `apiKey` in paginated requests  
`_fetch_aggs` sets `params = {}` after following `next_url`, then `_get()` appends `apiKey` to whatever params are passed. Polygon's `next_url` already contains all query parameters baked in (including `apiKey`), so the key ends up duplicated in the URL. Polygon accepts this, but it's slightly untidy. The `MASSIVE_API.md` reference doc notes: "next_url already has other params baked in" — the code should not re-add `apiKey` on paginated requests.

---

### 5.4 `get_latest_quote` returns bid == ask == 0.0 on Starter plan  
When `lastQuote` is absent (Starter plan), both bid and ask default to `0.0`. This is documented in a comment, but `0.0` is a sentinel that downstream consumers need to guard against. The plan's `PriceUpdate.mid` property handles this correctly by falling back to `last_price`, but the Quote object itself carrying zeros could cause divide-by-zero in spread calculations. Consider defaulting to `last_trade_price` instead of `0.0`.

---

## 6. Missing Implementations (Design → Reality Gap)

These components are fully specified in `MARKET_DATA_DESIGN.md` but do not yet exist in the codebase. They are Phase 2/3 work — this section tracks the gap so nothing gets forgotten.

| Component | File spec'd in design | Status |
|---|---|---|
| `PriceUpdate` dataclass | `price_update.py` | Not implemented |
| `PriceCache` (thread-safe, version counter) | `price_cache.py` | Not implemented |
| SSE streaming endpoint | `api/stream.py` | Not implemented |
| FastAPI lifespan + price refresh loop | `main.py` additions | Not implemented |
| Dependency injection helpers | `dependencies.py` | Not implemented |
| `CorrelatedMarketSimulator` | `market_simulator.py` additions | Not implemented |
| REST price endpoints (`/prices/snapshot`, `/prices/{ticker}`) | `api/prices.py` | Not implemented |

The design doc is comprehensive and well-thought-out. When implementing `PriceCache`, the single asyncio `Event` approach (rather than per-ticker events) correctly handles the small watchlist size, and the thread-safety note in the design about calling `asyncio.get_event_loop()` from a sync thread will need care — prefer `asyncio.get_running_loop()` inside `_notify()` and guard against `RuntimeError` for the no-loop case.

---

## 7. Test Coverage Gaps

These scenarios are not currently covered by any test:

| Gap | Risk |
|---|---|
| `daily_summary` with a historical `as_of` date verifying returned bars are on/before that date | Would have caught bug §4.2 |
| `get_bars` with `from_date > to_date` (empty/inverted range) | Undefined behavior in current code |
| `latest_bar` result date is ≤ today (not a future date) | Minor |
| `_db_bars` with `timespan="minute"` verifying `tf` conversion | Low risk |
| `MassiveProvider.get_bars` verifies exactly N HTTP requests for N tickers | Low risk |
| `MassiveProvider._get` on HTTP 500/502/503 (not retried currently) | Medium risk — only 429 is retried |

The last gap is notable: `MassiveProvider._get()` only retries on 429, not on transient 5xx errors. The design doc's `_RetryingSession` includes `RETRY_ON = {429, 500, 502, 503, 504}`, but the implemented `_get()` only checks `status_code == 429`. A transient 502 from a Polygon load balancer would raise immediately instead of being retried.

**Fix:** Change the retry condition:
```python
RETRY_ON = {429, 500, 502, 503, 504}

if response.status_code in RETRY_ON:
    time.sleep(2 ** attempt)
    continue
```

---

## 8. Summary Table

| # | Finding | Severity | Fix Required |
|---|---|---|---|
| 4.1 | DB replay tests fail without sqlalchemy in env | Low | Add to test deps |
| 4.2 | `daily_summary` ignores `as_of` — lookahead risk | **High** | Pass `as_of` to `get_bars` |
| 4.3 | `pd.Timestamp.utcnow()` deprecated (16 warnings) | Low | Use `pd.Timestamp.now("UTC")` |
| 5.1 | Unused imports (`Optional`, `BDay`) | Low | Delete imports |
| 5.2 | `get_snapshot` always uses `date.today()` for `Bar.date` | Low | Use snapshot timestamp |
| 5.3 | `apiKey` duplicated on paginated requests | Low | Skip re-adding on `next_url` |
| 5.4 | `get_latest_quote` defaults to `0.0` bid/ask | Low | Default to last trade price |
| 7 | 5xx errors not retried in `MassiveProvider._get` | Medium | Extend retry to `{429,500,502,503,504}` |

---

## 9. Verdict

The market data backend is in good shape. The interface design, GBM simulator, and test suite are all production-quality for a capstone project. The critical issue to fix before the backtester is built is **§4.2** (`daily_summary` ignoring `as_of`) — if left unfixed, every backtest that calls `daily_summary` will see today's data rather than historical data, invalidating the backtest entirely. All other findings are quality improvements rather than blockers.

The unimplemented SSE/cache layer (§6) is the natural next step per the plan and is well-specified in `MARKET_DATA_DESIGN.md`.
