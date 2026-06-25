# AI Trading Workstation

## What This Is

An AI-assisted research and paper-trading platform for US stocks/ETFs. It pulls historical and live market data for a watchlist, engineers technical features and generates an XGBoost ML signal per symbol per day, feeds that signal plus recent price action and news headlines to an LLM (Cerebras `gpt-oss-120b`), which outputs a structured trade decision with a plain-English rationale, then backtests that combined ML+LLM strategy and runs it live against Alpaca's paper trading API — everything surfaced in a React dashboard. This is a capstone/portfolio project for a single operator; no real money is ever touched.

## Core Value

The LLM override story: when the AI's rationale explains why it ignored a strong quant signal because of negative news or risk flags, that is the demo — everything else serves this moment.

## Requirements

### Validated

- ✓ Market data provider abstraction (ABC + factory `create_provider()`) — existing
- ✓ MassiveProvider: live OHLCV from Polygon/Massive REST API with exponential backoff — existing
- ✓ SimulatorProvider + MarketSimulator: GBM synthetic fallback + DB replay — existing
- ✓ Provider selection via env var (`MASSIVE_API_KEY` present → live, absent → simulator) — existing

### Active

- [ ] All SQLAlchemy models (instruments, price_bars, news_articles, ml_signals, llm_decisions, trades, positions, portfolio_snapshots, backtest_runs) with correct indexes and Alembic migrations
- [ ] Historical data ingestion: yfinance loader (2-5 yr backfill, auto_adjust), Alpaca live bars loader, NewsAPI headlines loader
- [ ] FastAPI application skeleton with routers, Pydantic schemas, error handling, logging middleware, and SSE stub
- [ ] Feature engineering: full indicator set (returns, SMA/EMA, RSI, MACD, BB, volatility, volume z-score) with no-lookahead guarantee
- [ ] ML signal model: XGBoost trained with walk-forward validation, versioned artifacts, inference function shared by backtester and live executor
- [ ] LLM reasoning layer: context assembly, Cerebras API call with structured output, Pydantic response validation, decision cache check, full prompt/response logging
- [ ] Backtesting engine: day-by-day event-driven replay, D+1 fill simulation, all metrics (CAGR, Sharpe, max drawdown, win rate), shuffle sanity check, SPY baseline comparison
- [ ] Paper trading executor: Alpaca paper order placement, risk checks (MAX_POSITION_PCT, MAX_POSITIONS, DAILY_LOSS_LIMIT_PCT), startup paper-endpoint assertion, APScheduler daily job
- [ ] React dashboard: Dashboard, Signals, Trades, Backtests, Settings pages wired to real backend; candlestick chart, equity curve, signal/decision cards; paper-trading disclaimer
- [ ] Test suite: pytest covering features, ML inference, LLM parsing (mocked), backtest metrics, risk checks, key API endpoints; frontend vitest for Signals and Dashboard
- [ ] Docker + docker-compose (backend + Postgres + frontend); deployment to Render/Railway + Vercel; GitHub Actions CI; production cron job
- [ ] README with setup instructions, architecture summary, screenshots; honest backtest write-up; 5-10 min demo script

### Out of Scope

- Live/real-money brokerage execution — paper trading only, always; startup assertion enforces this
- Multi-user auth system — single operator
- Fundamentals ingestion (SEC filings, earnings) — news headlines are sufficient for the LLM context
- Intraday or sub-daily signals — daily bars only
- Non-US instruments — watchlist is US stocks/ETFs only (yfinance and Alpaca coverage)

## Context

- **Existing code:** Market data layer built in `backend/app/services/data_ingestion/` — 4 Python files implementing the `MarketDataProvider` ABC, `MassiveProvider` (Polygon REST), and `MarketSimulator`/`SimulatorProvider` (GBM + DB replay). No other backend or frontend source code yet (frontend `dist/` exists but no `src/`).
- **Critical design constraint:** Backtester and live executor must call the exact same `features → ML signal → LLM decision` function (`services/decision.py`). Any divergence invalidates the backtest — this is the central architectural rule.
- **LLM rate limits:** Cerebras free tier is 5 RPM / 1M tokens/day. Decision cache in `llm_decisions` table (unique key: `instrument_id + as_of_date + model_slug + prompt_version`) is mandatory for backtesting. Without it, multi-year backtests exhaust the rate limit.
- **Tech stack fixed:** Python 3.11+, FastAPI, SQLAlchemy + PostgreSQL, Alembic, XGBoost, `openai` SDK pointed at Cerebras, `alpaca-py`, React + Vite + TypeScript, Tailwind, `lightweight-charts`, `recharts`.
- **Demo audience:** Technical evaluators (ML rigor and code quality); polish test coverage, validation metrics, and the LLM override story first; UI polish is secondary.

## Constraints

- **Paper trading only:** `ALPACA_BASE_URL` must equal `https://paper-api.alpaca.markets`; startup assertion in `trading/executor.py` must refuse to start otherwise.
- **No lookahead:** All feature computation and LLM news queries must use data with `timestamp <= as_of_date`; never use `datetime.now()` as the upper bound in backtest context.
- **LLM API:** Cerebras only — `openai` SDK with `base_url=https://api.cerebras.ai/v1`, `api_key=LLM_API_KEY`, model `gpt-oss-120b`.
- **No secrets in git:** Only `.env.example` (with placeholders) is committed; `.env` is git-ignored.
- **Forward-return label:** Fixed at 5 trading days; do not change after first training run.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| LLM model: `gpt-oss-120b` via Cerebras | Free tier, ~3000 tok/s, OpenAI-compatible | — Pending |
| Forward-return label: 5 trading days (fixed) | Best signal/noise at daily-bar resolution | — Pending |
| Backtest fill price: D+1 open | Realistic; avoids same-bar lookahead | — Pending |
| LLM is final authority; ML score is one input | Core demo narrative: AI overrides quant signal for news reason | — Pending |
| Decision cache: unique index on (instrument_id, as_of_date, model_slug, prompt_version) | Mandatory for backtesting under rate limits; re-runs never re-call API | — Pending |
| Adjusted prices: `Adj Close` from yfinance (`auto_adjust=True`) | Raw close produces phantom signals around splits/dividends | — Pending |
| NaN handling: drop rows (first ~50 bars/symbol = warmup) | Forward-fill introduces lookahead | — Pending |
| Shared decision function in `services/decision.py` | Backtester and live executor import same function | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-25 after initialization*
