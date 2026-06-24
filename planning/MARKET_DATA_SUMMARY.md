# Market Data Backend — Build & Review Summary

**Date:** 2026-06-24  
**Phase covered:** Phase 2 — Historical Data Ingestion (market data subsystem)  
**Status:** ✅ Complete — all tests green, fixes applied, demo running

---

## 1. What Was Built

A unified market data layer that supplies OHLCV price data to every consumer in the system — feature engineering, the backtester, and the live executor — through a single abstract interface. No consumer ever imports a provider directly; they all call `create_provider()` and get whatever is appropriate for the environment.

### Files created

```
backend/app/services/data_ingestion/
├── market_interface.py      Bar, Quote dataclasses + MarketDataProvider ABC + create_provider()
├── market_simulator.py      MarketSimulator  — DB replay mode + GBM synthetic fallback
├── simulator_provider.py    SimulatorProvider — thin MarketDataProvider wrapper
└── massive_provider.py      MassiveProvider  — live Polygon/Massive REST API client

tests/backend/
├── test_market_interface.py    14 tests
├── test_market_simulator.py    65 tests  (inc. 8 new after review)
├── test_massive_provider.py    27 tests  (inc. 5 new after review)
└── test_simulator_provider.py  27 tests
                                ─────────
                                123 tests total — all passing

market_data_demo.py              live terminal dashboard (root of repo)
planning/MARKET_DATA_SUMMARY.md  this file
planning/archive/                completed design & review docs
```

---

## 2. Architecture

```
Caller (feature engineering / backtester / executor)
        │
        ▼
create_provider()          ← only place that reads MASSIVE_API_KEY
        │
        ├── MASSIVE_API_KEY set?  YES → MassiveProvider
        │                               Polygon/Massive REST API
        │                               Exponential backoff on 429 + 5xx
        │                               Handles pagination (next_url)
        │
        └── MASSIVE_API_KEY absent?  → SimulatorProvider
                                        │
                                        ├── DB session provided + rows exist?
                                        │       YES → DB Replay (price_bars table)
                                        │
                                        └── NO → Synthetic GBM
                                                  Per-ticker deterministic seed
                                                  Correlated daily vol params
                                                  Price floor $0.01
```

### Provider interface (`MarketDataProvider` ABC)

| Method | Returns | Used by |
|---|---|---|
| `get_bars(tickers, from_date, to_date)` | `dict[str, pd.DataFrame]` | Feature engineering, backtester |
| `get_snapshot(tickers)` | `dict[str, Bar]` | Live executor (open position pricing) |
| `get_latest_quote(tickers)` | `dict[str, Quote]` | SSE streaming layer (future) |
| `get_daily_market_summary(as_of)` | `dict[str, Bar]` | Bulk historical ingestion |

### Data model

**`Bar`** — frozen dataclass; one OHLCV record. Always adjusted prices (no split/dividend artefacts).  
**`Quote`** — frozen dataclass; best bid/ask at a point in time.  
Both are immutable and hashable — safe to cache, share across threads, put in sets.

---

## 3. Design Decisions Made

| Decision | Choice | Reason |
|---|---|---|
| Interface abstraction | `MarketDataProvider` ABC | Backtester and executor never change when provider changes |
| Provider selection | Env var `MASSIVE_API_KEY` in `create_provider()` | Single location; CI automatically uses simulator |
| GBM seed strategy | `ticker_seed XOR global_seed` | Same ticker deterministic; different instances can diverge |
| Simulation origin | `2020-01-02` | Far enough back for 2-year backtests without generating extra data |
| DB replay fallback | `price_bars` via SQLAlchemy | Backtester uses real ingested data when available, GBM only in CI |
| Retry strategy | Exponential backoff `2^attempt` seconds | Matches Polygon's guidance; jitter omitted for simplicity |
| Retry set | `{429, 500, 502, 503, 504}` | Catches both rate limits and transient infra failures |
| VWAP in DB replay | Always `None` | `price_bars` schema doesn't store VWAP; avoids silent zero |
| `Bar.date` in `get_snapshot` | Derived from `updated` nanosecond timestamp | Avoids `date.today()` which breaks for after-hours or stale data |
| `get_latest_quote` fallback | `lastTrade.p` when `lastQuote` absent | Starter plan has no real-time quotes; 0.0 would crash spread calculations |

---

## 4. Code Review — Findings & Fixes

A full review was performed after initial implementation. Seven issues were found and fixed in branch `fix/market-data-review-issues`.

### Issues fixed

| Severity | Location | Issue | Fix applied |
|---|---|---|---|
| HIGH | `market_simulator.py:daily_summary` | `as_of` date ignored — always returned today's bars, causing lookahead bias for the backtester | Passes `as_of` to `get_bars()` for every ticker |
| MED | `massive_provider.py:_get` | Only `429` was retried; transient `500/502/503/504` raised immediately | Extended retry set to all five status codes |
| LOW | `massive_provider.py:get_latest_quote` | Defaulted to `0.0` bid/ask on Starter plan (no `lastQuote`) | Falls back to `lastTrade.p` |
| LOW | `massive_provider.py:get_snapshot` | `Bar.date` hardcoded to `date.today()` | Derived from snapshot `updated` nanosecond timestamp |
| LOW | `massive_provider.py:_get` | `apiKey` appended as query param even when already embedded in `next_url` | Checks if `apiKey` is in the URL before adding |
| LOW | `market_simulator.py:latest_quote` | `pd.Timestamp.utcnow()` deprecated in pandas 4 (16 warnings per test run) | Changed to `pd.Timestamp.now("UTC")` |
| LOW | `market_simulator.py` imports | `Optional` and `BDay` imported but never used | Removed |

### New tests added (8)

| Test | What it guards |
|---|---|
| `test_respects_as_of_date_no_lookahead` | `daily_summary` bars must be dated ≤ `as_of` |
| `test_different_as_of_dates_differ` | Different historical dates produce different prices |
| `test_inverted_range_returns_empty` | `from_date > to_date` returns empty DataFrame, no exception |
| `test_future_from_date_before_sim_origin_returns_empty` | Pre-origin requests return empty |
| `test_retries_on_502_then_succeeds` | 5xx retry path actually retries |
| `test_raises_after_max_5xx_retries` | 5xx exhaustion raises `RuntimeError` |
| `test_date_derived_from_updated_timestamp` | `Bar.date` matches the `updated` ns timestamp |
| `test_starter_plan_falls_back_to_last_trade_price` | No-quote path uses `lastTrade.p`, not `0.0` |

### Final test results

```
123 passed, 0 failed, 0 warnings   (5.2 s)
```

---

## 5. GBM Simulator — Guarantees

| Property | Guarantee |
|---|---|
| Schema | Identical columns to `MassiveProvider`: `date, open, high, low, close, volume, vwap` |
| No lookahead | `get_bars(ticker, from, to)` never returns rows with `date > to` |
| Determinism | Same ticker + same seed → same path every run |
| OHLC invariants | `high ≥ open`, `high ≥ close`, `low ≤ open`, `low ≤ close`; all enforced by construction |
| Positive prices | Hard floor $0.01; exponential GBM cannot go negative |
| Business days only | Uses `pd.bdate_range` — no Saturdays or Sundays in output |
| `daily_summary` | Returns bars on or before `as_of`, not today's bars |

---

## 6. Terminal Demo

`market_data_demo.py` (project root) runs a full live dashboard in the terminal using the `SimulatorProvider` — no API key needed.

```
python market_data_demo.py                   # 60 ticks at 0.4 s each
python market_data_demo.py --ticks 0         # run until Ctrl-C
python market_data_demo.py --ticks 120 --interval 0.2
```

**Requires:** `pip install rich`

**Dashboard panels:**
- **Price table** — symbol, price, `$` change, `%` change, sparkline (▁▂▃▄▅▆▇█), volume, bid, ask, spread; colour-coded arrows (↑ green / ↓ red / → grey)
- **Event log** — auto-detected moves ≥1.5 % get a 📈/📉 entry; moves ≥3.0% get ⚡
- **Session summary** — top gainer, top loser, most active by volume; updates every tick

---

## 7. What Is Still To Build (MARKET_DATA_DESIGN.md)

The SSE streaming layer described in `planning/MARKET_DATA_DESIGN.md` is not yet implemented. These files still need to be created:

```
backend/app/services/data_ingestion/
├── price_update.py    PriceUpdate frozen dataclass + constructors
└── price_cache.py     PriceCache (thread-safe, version counter, asyncio Event)

backend/app/
├── dependencies.py    get_price_cache(), get_watchlist() FastAPI dependencies
└── api/
    ├── prices.py      GET /prices/snapshot, GET /prices/{ticker}
    └── stream.py      GET /stream/prices  (SSE, EventSource-compatible)
```

Also not yet implemented: `CorrelatedMarketSimulator` (correlated GBM paths for risk testing).

These are Phase 3 tasks once the FastAPI backend skeleton (Phase 3 in `plan.md`) is wired up.

---

## 8. Planning Files — Archive Status

| File | Status |
|---|---|
| `planning/plan.md` | **Active** — main project checklist |
| `planning/MARKET_DATA_DESIGN.md` | **Active** — SSE/cache layer still to implement |
| `planning/archive/MARKET_INTERFACE.md` | Archived — fully implemented |
| `planning/archive/MARKET_SIMULATOR.md` | Archived — fully implemented |
| `planning/archive/MASSIVE_API.md` | Archived — fully implemented |
| `planning/archive/MARKET_DATA_REVIEW.md` | Archived — all findings resolved |
