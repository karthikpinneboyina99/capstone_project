# External Integrations

**Last mapped:** 2026-06-25
**Focus:** External APIs, services, databases, auth providers

---

## Market Data — Massive / Polygon.io

**Purpose:** Primary source of OHLCV bar data and quotes for US stocks/ETFs.

**Env vars:**
- `MASSIVE_API_KEY` — Polygon.io REST API key (leave blank to use SimulatorProvider)
- `MASSIVE_BASE_URL` — Override REST base (default: `https://api.polygon.io`)

**Usage:** `backend/app/services/data_ingestion/massive_provider.py`
- `MassiveProvider.get_bars(tickers, from_date, to_date, timespan)` — OHLCV bars
- `MassiveProvider.get_quotes(ticker)` — latest bid/ask quote
- Uses exponential backoff (`time.sleep`) on 429 responses
- Reference: `planning/MASSIVE_API.md`

**Fallback:** When `MASSIVE_API_KEY` is empty, `SimulatorProvider` (GBM synthetic data) is used instead — no network calls.

---

## Alpaca — Paper Trading

**Purpose:** Paper trade order submission and account management.

**Env vars:**
- `ALPACA_API_KEY` — Paper account key ID
- `ALPACA_SECRET_KEY` — Paper account secret key
- `ALPACA_BASE_URL` — Must be `https://paper-api.alpaca.markets` (real-money endpoint must never be used)

**Package:** `alpaca-py`

**Usage:** Planned for `backend/app/services/trading/` (not yet implemented as source — only `.pyc` exists)

**Safety rule:** Startup assertion required that `ALPACA_BASE_URL` is the paper endpoint.

---

## Cerebras — LLM Reasoning

**Purpose:** LLM-generated trade decision rationale and explainability.

**Env vars:**
- `LLM_API_KEY` — Cerebras API key
- `LLM_BASE_URL` — `https://api.cerebras.ai/v1` (OpenAI-compatible)
- `LLM_MODEL` — `gpt-oss-120b`

**Package:** `openai` (pointed at Cerebras base URL)

**Rate limits (free tier):**
- 5 RPM
- 30K input tokens/min
- 1M tokens/day

**Critical:** Decision cache (planned in `planning/plan.md` section 9) is **mandatory** for backtesting; hitting the LLM on every bar will exhaust the daily quota in minutes.

**Usage:** Planned for `backend/app/services/llm_reasoning/` (only `.pyc` exists)

---

## NewsAPI — Optional Context

**Purpose:** News headlines as optional context injected into LLM prompts.

**Env vars:**
- `NEWS_API_KEY` — NewsAPI.org key (optional; feature degrades gracefully when absent)

**Usage:** Planned; not yet implemented in source.

---

## Financial Modeling Prep (FMP) — Optional Fundamentals

**Purpose:** Fundamentals data (P/E, EPS, etc.) as optional LLM context.

**Env vars:**
- `FMP_API_KEY` — FMP key (optional)

**Usage:** Planned; not yet implemented in source.

---

## yfinance — Supplemental Market Data

**Purpose:** Supplemental/fallback market data (Yahoo Finance). Used for ticker metadata and price history that doesn't require a Polygon key.

**Package:** `yfinance`

**Usage:** Available as a provider fallback. Referenced in `backend/requirements.txt`.

---

## PostgreSQL — Primary Database

**Purpose:** Stores OHLCV bars, ML features, trade decisions, backtest results, positions.

**Env vars:**
- `DATABASE_URL` — `postgresql://postgres:postgres@localhost:5432/trading_workstation`

**Packages:** `sqlalchemy`, `psycopg2-binary`, `alembic`

**Status:** Schema not yet implemented as source (no `migrations/` directory, no `schema.sql`). Plan specifies TimescaleDB extension for time-series optimization.

---

## GitHub Actions — CI

**Files:**
- `.github/workflows/claude.yml` — Claude Code integration
- `.github/workflows/claude-code-review.yml` — Automated code review on PRs

**Usage:** Automated review; no deployment pipeline yet.

---

## Summary

| Integration | Type | Status | Env Var |
|-------------|------|--------|---------|
| Massive/Polygon.io | Market data REST | Implemented | `MASSIVE_API_KEY` |
| SimulatorProvider (GBM) | Market data fallback | Implemented | — |
| Alpaca | Paper trading | Planned (`.pyc` only) | `ALPACA_API_KEY` |
| Cerebras | LLM reasoning | Planned (`.pyc` only) | `LLM_API_KEY` |
| NewsAPI | News context | Planned | `NEWS_API_KEY` |
| FMP | Fundamentals | Planned | `FMP_API_KEY` |
| yfinance | Supplemental data | Available | — |
| PostgreSQL | Primary database | Planned (no schema) | `DATABASE_URL` |
| GitHub Actions | CI | Active | — |
