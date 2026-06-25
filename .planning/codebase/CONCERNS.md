# Codebase Concerns

**Last mapped:** 2026-06-25
**Focus:** Technical debt, known issues, security, performance, fragile areas

---

## 🔴 Critical Issues

### Missing Source Files — Only Bytecode Present

**Severity:** CRITICAL — blocks all development beyond the market data layer.

Almost all backend source files exist only as `.pyc` bytecode in `__pycache__/`. Only 4 `.py` source files are present (the market data layer). All other phases are missing source:

- `main.py` — missing
- `core/config.py` — missing
- `db/session.py` — missing
- All SQLAlchemy models — missing
- All Pydantic schemas — missing
- All FastAPI routers — missing
- ML feature/signal pipeline — missing
- LLM reasoning layer — missing
- Backtesting engine — missing
- Paper trading executor — missing

**Impact:** The project cannot be developed or modified beyond the market data layer without first creating these source files from scratch (following `planning/plan.md`).

**Resolution:** These components are the next phases of the build per `planning/plan.md`. Build them in order per the phase checklist.

---

### No Database Schema / Migrations

**Severity:** CRITICAL — database cannot be initialized.

No `schema.sql`, no Alembic `migrations/` directory, no `alembic.ini`. The database schema from `planning/plan.md` has not been committed to code.

---

## 🟠 High Priority

### Frontend Source Code Missing

Only a compiled `dist/` bundle is present under the frontend directory; `src/` is absent. Frontend cannot be modified or rebuilt without source recovery.

### No Infrastructure Files

No `docker-compose.yml`, no `Dockerfile`, no deployment configuration. The plan specifies Docker deployment but no container definitions exist.

### Unversioned Dependencies

`requirements.txt` has no pinned versions for any package (all entries unversioned). This will cause non-deterministic installs and potential breakage when package APIs change.

**Affected file:** `requirements.txt`

---

## 🟡 Medium Priority

### Blocking `time.sleep` in Async Context

**File:** `backend/data/providers/massive_provider.py`

`time.sleep()` is used for retry backoff. If called from a FastAPI async route (via `await`-less path), this blocks the event loop and stalls all other requests. Should use `asyncio.sleep()`.

### MarketSimulator Signature Mismatch

**File:** `backend/data/providers/market_simulator.py`

`MarketSimulator.get_bars()` takes a singular ticker string while the `MarketDataProvider` abstract base class expects a list. This violates the Liskov Substitution Principle and will cause runtime errors if the simulator is swapped in for the real provider.

### `daily_summary` Hardcoded to 10 Tickers

**File:** `backend/data/` (market data service)

`daily_summary` silently drops any watchlist symbols beyond the first 10. No error or warning is raised for symbols outside this limit.

### Sequential HTTP Fetches

Ticker data is fetched sequentially rather than in parallel. For a watchlist with many symbols, this creates unnecessary latency. Should use `asyncio.gather()` or a thread pool.

### GBM Synthetic Path Regenerates from Fixed Date

**File:** `backend/data/providers/market_simulator.py`

The GBM-based synthetic price path regenerates from `2020-01-02` on every call regardless of the requested date range. This makes the simulator deterministic only within a session — not across calls.

### `tenacity` Missing from Requirements

The `planning/plan.md` recommends `tenacity` for LLM retry logic, but it is not in `requirements.txt`. Will fail at import time when the LLM layer is built.

---

## 🔐 Security Concerns

### API Key in URL Query Params

**File:** `backend/data/providers/massive_provider.py`

Polygon.io's `next_url` pagination passes the API key as a URL query parameter. This means the key appears in server logs, browser history, and HTTP access logs. Should strip and re-inject the key as a header instead of following the raw `next_url`.

### No Alpaca Paper Endpoint Assertion Verifiable

The `planning/plan.md` requires an assertion at startup that the Alpaca base URL is the paper endpoint (`https://paper-api.alpaca.markets`). Since `main.py` is missing, this assertion cannot be verified as implemented.

---

## ⚡ Performance Concerns

### Cerebras Rate Limit vs Backtesting Scope

The Cerebras free tier is rate-limited to 5 RPM and 1M tokens/day. A multi-year backtest with daily decisions would exhaust the rate limit in minutes without the decision cache specified in `planning/plan.md` section 9. The cache is **mandatory** before backtesting runs.

---

## 📊 Test Coverage

Only 4 test files exist, all covering the market data layer:

- `tests/test_market_data_service.py`
- `tests/test_providers.py`
- `tests/test_polygon_provider.py`
- `tests/test_massive_provider.py`

**Coverage gaps:** All layers beyond market data have zero test coverage — database models, ML pipeline, LLM reasoning, backtester, paper trading executor, and React frontend.

---

## 📝 Minor Issues

- `daily_summary` and other hardcoded values should be driven by config/env vars
- No `.env.example` validation (startup doesn't check that required env vars are set)

---

## Summary

| Severity | Count | Key Issues |
|----------|-------|------------|
| 🔴 Critical | 2 | Missing source files, no DB schema |
| 🟠 High | 3 | Missing frontend src, no infra files, unversioned deps |
| 🟡 Medium | 6 | Async/blocking, signature mismatch, hardcoded limits |
| 🔐 Security | 2 | API key in URL, missing paper endpoint assertion |
| ⚡ Performance | 1 | Cerebras rate limit vs backtest scope |
