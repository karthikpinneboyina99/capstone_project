# Requirements: AI Trading Workstation

**Defined:** 2026-06-25
**Core Value:** The LLM override story — when the AI's rationale explains why it ignored a strong quant signal due to negative news or risk flags, that is the demo centerpiece.

## v1 Requirements

### Data Foundation

- [ ] **DATA-01**: System stores all SQLAlchemy ORM models (instruments, price_bars, news_articles, ml_signals, llm_decisions, trades, positions, portfolio_snapshots, backtest_runs) with correct foreign keys, indexes, and a TimestampMixin
- [ ] **DATA-02**: Alembic is initialized; the first migration is generated and applied; `database/schema.sql` is auto-generated via `pg_dump --schema-only`
- [ ] **DATA-03**: Operator can backfill 2-5 years of daily OHLCV for the watchlist via yfinance (adjusted close only, `auto_adjust=True`) into `price_bars`
- [ ] **DATA-04**: System ingests latest daily bars via Alpaca live data API (`alpaca-py`) for the daily scheduled job
- [ ] **DATA-05**: System ingests news headlines per watchlist symbol via NewsAPI into `news_articles` (100 req/day free tier; fundamentals are out of scope)
- [ ] **DATA-06**: Watchlist is defined (5-15 liquid large-cap US symbols, e.g., AAPL, MSFT, NVDA, SPY, QQQ) and stored in the `instruments` table

### API & Backend

- [ ] **API-01**: FastAPI application starts cleanly with routers for instruments/watchlist, price data, signals, decisions, trades, positions, portfolio, and backtests
- [ ] **API-02**: All request/response types use Pydantic schemas mirroring the DB models
- [ ] **API-03**: Backend includes error handling middleware and structured logging
- [ ] **API-04**: `GET /stream/portfolio` SSE endpoint exists and pushes live portfolio updates to the React dashboard

### Feature Engineering

- [ ] **FEAT-01**: System computes the full indicator set per symbol per day from `price_bars`: 1d/5d/20d returns, SMA(10/20/50), EMA(12/26), price-relative-to-MA, RSI(14), MACD(line/signal/histogram), Bollinger Bands(20,2σ: %B and bandwidth), 20d rolling volatility, volume z-score vs 20d lagged average, day-of-week
- [ ] **FEAT-02**: Feature computation never accesses bars with `timestamp > as_of_date` (no-lookahead guarantee)
- [ ] **FEAT-03**: All features are unit-tested against hand-computed expected values on a small fixture dataset
- [ ] **FEAT-04**: NaN rows (first ~50 bars/symbol warmup) are dropped; no forward-fill is used

### ML Signal Model

- [ ] **ML-01**: XGBoost regressor predicts 5-day forward return using walk-forward (expanding window) time-series splits; never sklearn shuffle-based K-fold
- [ ] **ML-02**: Model artifacts are saved as versioned files (`backend/models/xgb_v1.json` + scaler); scaler is fitted only on training data within each fold
- [ ] **ML-03**: Inference function (`services/ml/predict.py`) loads a versioned artifact and returns a normalized signal score for (symbol, as_of_date) using only data available as of that date
- [ ] **ML-04**: Out-of-sample validation metrics are documented (MAE/RMSE or directional accuracy), even if mediocre

### LLM Decision Engine

- [ ] **LLM-01**: System assembles context per (symbol, as_of_date): ML signal score + top-3 features, recent 5-10 day price action summary, 3-5 most recent news headlines (filtered `published_at <= as_of_date`), current position and portfolio risk constraints
- [ ] **LLM-02**: System calls `gpt-oss-120b` via Cerebras (`https://api.cerebras.ai/v1`) using the `openai` SDK with structured output; response is validated by a Pydantic model: `{action, position_size_pct, confidence, rationale, risk_flags}`
- [ ] **LLM-03**: Before every LLM call, system checks `llm_decisions` for a matching `(instrument_id, as_of_date, model_slug, prompt_version)` row; cache hit returns stored decision without API call
- [ ] **LLM-04**: Every decision and full raw prompt+response is persisted to `llm_decisions`; malformed responses are logged and handled gracefully, not silently producing bad decisions
- [ ] **LLM-05**: LLM client uses `tenacity` exponential backoff on 429 responses (`min=4s, max=60s`)
- [ ] **LLM-06**: Unit tests mock the OpenAI client and verify parsing/validation logic including malformed-response handling; real API is never called in the test suite

### Backtesting Engine

- [ ] **BACK-01**: Engine runs a day-by-day event-driven replay over a configurable date range; fills are simulated at next trading day's D+1 open (never same-bar close)
- [ ] **BACK-02**: Engine calls the exact same shared decision function as the live executor (`services/decision.py`); no duplicate logic
- [ ] **BACK-03**: Engine computes all required metrics: total return, CAGR, annualized Sharpe ratio (using daily portfolio returns), max drawdown, win rate, avg win/loss, num trades
- [ ] **BACK-04**: Shuffle sanity check: performance collapses when signals are randomized (verifies no lookahead bias)
- [ ] **BACK-05**: At least one full backtest run is stored in `backtest_runs` with results compared against a SPY buy-and-hold baseline over the same period
- [ ] **BACK-06**: Backtest metrics module is unit-tested against hand-computed examples (especially Sharpe and max drawdown)

### Paper Trading Executor

- [ ] **TRADE-01**: `services/trading/executor.py` asserts `ALPACA_BASE_URL == https://paper-api.alpaca.markets` at startup and refuses to run otherwise
- [ ] **TRADE-02**: Daily job runs the same feature→ML signal→LLM decision pipeline as the backtester per watchlist symbol and submits paper orders via `alpaca-py`
- [ ] **TRADE-03**: Risk checks enforced: MAX_POSITION_PCT (10%), MAX_POSITIONS (8), DAILY_LOSS_LIMIT_PCT (3%); all configurable via env vars
- [ ] **TRADE-04**: Risk checks are unit-tested independently with mocked Alpaca API
- [ ] **TRADE-05**: Daily scheduled job (APScheduler) runs reliably for at least several consecutive trading days with logged decisions and trades; manual verification against Alpaca paper dashboard

### Frontend Dashboard

- [ ] **UI-01**: Dashboard page shows portfolio value, today's P&L, equity curve chart (recharts), and open positions table; all data from live backend (no mock data)
- [ ] **UI-02**: Signals page shows today's ML signal + LLM decision per watchlist symbol with the rationale text visible and expandable; this is the primary demo page
- [ ] **UI-03**: Trades page shows full paper trade history filterable by symbol and date
- [ ] **UI-04**: Backtests page allows triggering a new backtest run (date range, params) and displays results: equity curve, metrics table, comparison vs buy-and-hold
- [ ] **UI-05**: Settings page shows watchlist and risk parameter display (read-only)
- [ ] **UI-06**: Candlestick chart (`lightweight-charts`) available for any selected symbol
- [ ] **UI-07**: All pages handle loading, error, and empty states — not just the happy path
- [ ] **UI-08**: A visible, persistent disclaimer: "Paper trading only — not financial advice" on every page
- [ ] **UI-09**: Responsive enough to demo on a laptop screen

### Testing

- [ ] **TEST-01**: `pytest` suite covers feature computation, ML inference, LLM response parsing (mocked), backtest metrics, risk checks, and key API endpoints (httpx TestClient)
- [ ] **TEST-02**: Frontend vitest suite covers at least the Signals and Dashboard components
- [ ] **TEST-03**: `pytest` and `npm test` both green before any phase is marked complete

### Infrastructure & Deployment

- [ ] **INFRA-01**: `backend/Dockerfile`, `frontend/Dockerfile`, and root `docker-compose.yml` (backend + Postgres + frontend) are written; `docker-compose up` brings up the full stack locally
- [ ] **INFRA-02**: Backend + Postgres deployed to Render or Railway; frontend deployed to Vercel; env vars/secrets set on each platform (never in the repo)
- [ ] **INFRA-03**: Production daily job configured (Render Cron Job or scheduled GitHub Actions workflow hitting the deployed endpoint)
- [ ] **INFRA-04**: GitHub Actions CI workflow runs `pytest` and frontend tests/build on every push

### Documentation

- [ ] **DOC-01**: Root `README.md` has setup instructions, architecture summary, and screenshots
- [ ] **DOC-02**: Backtest results honestly documented (including underperformance vs buy-and-hold if applicable) — analytical rigor matters more than beating the market
- [ ] **DOC-03**: 5-10 minute demo script prepared: Signals page with LLM rationale → backtest run → live paper trade end-to-end → test suite passing

## v2 Requirements

### Stretch Goals

- **STRETCH-01**: PyTorch LSTM/sequence model compared against XGBoost baseline
- **STRETCH-02**: Real-time intraday signal updates (sub-daily bars)
- **STRETCH-03**: Fundamental data ingestion (earnings, balance sheet) as additional LLM context
- **STRETCH-04**: Multi-user auth and role-based access

## Out of Scope

| Feature | Reason |
|---------|--------|
| Live/real-money brokerage execution | Paper trading only — startup assertion enforces this; building a live path adds real financial risk |
| Multi-user authentication | Single operator; auth complexity would dominate the capstone timeline |
| Fundamentals ingestion (SEC filings, earnings) | News headlines sufficient for LLM context; fundamentals are quarterly and add schema complexity with marginal daily-signal value |
| Intraday / sub-daily signals | Daily bars only; intraday requires paid data and much higher complexity |
| Non-US instruments | yfinance and Alpaca coverage; watchlist is US stocks/ETFs only |
| Non-paper Alpaca order paths | No live brokerage client class even built — removes temptation and risk entirely |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| DATA-01 | Phase 1 | Pending |
| DATA-02 | Phase 1 | Pending |
| DATA-03 | Phase 2 | Pending |
| DATA-04 | Phase 2 | Pending |
| DATA-05 | Phase 2 | Pending |
| DATA-06 | Phase 2 | Pending |
| API-01 | Phase 3 | Pending |
| API-02 | Phase 3 | Pending |
| API-03 | Phase 3 | Pending |
| API-04 | Phase 8 | Pending |
| FEAT-01 | Phase 4 | Pending |
| FEAT-02 | Phase 4 | Pending |
| FEAT-03 | Phase 4 | Pending |
| FEAT-04 | Phase 4 | Pending |
| ML-01 | Phase 5 | Pending |
| ML-02 | Phase 5 | Pending |
| ML-03 | Phase 5 | Pending |
| ML-04 | Phase 5 | Pending |
| LLM-01 | Phase 6 | Pending |
| LLM-02 | Phase 6 | Pending |
| LLM-03 | Phase 6 | Pending |
| LLM-04 | Phase 6 | Pending |
| LLM-05 | Phase 6 | Pending |
| LLM-06 | Phase 6 | Pending |
| BACK-01 | Phase 7 | Pending |
| BACK-02 | Phase 7 | Pending |
| BACK-03 | Phase 7 | Pending |
| BACK-04 | Phase 7 | Pending |
| BACK-05 | Phase 7 | Pending |
| BACK-06 | Phase 7 | Pending |
| TRADE-01 | Phase 8 | Pending |
| TRADE-02 | Phase 8 | Pending |
| TRADE-03 | Phase 8 | Pending |
| TRADE-04 | Phase 8 | Pending |
| TRADE-05 | Phase 8 | Pending |
| UI-01 | Phase 9 | Pending |
| UI-02 | Phase 9 | Pending |
| UI-03 | Phase 9 | Pending |
| UI-04 | Phase 9 | Pending |
| UI-05 | Phase 9 | Pending |
| UI-06 | Phase 9 | Pending |
| UI-07 | Phase 9 | Pending |
| UI-08 | Phase 9 | Pending |
| UI-09 | Phase 9 | Pending |
| TEST-01 | Phase 10 | Pending |
| TEST-02 | Phase 10 | Pending |
| TEST-03 | Phase 10 | Pending |
| INFRA-01 | Phase 11 | Pending |
| INFRA-02 | Phase 11 | Pending |
| INFRA-03 | Phase 11 | Pending |
| INFRA-04 | Phase 11 | Pending |
| DOC-01 | Phase 12 | Pending |
| DOC-02 | Phase 12 | Pending |
| DOC-03 | Phase 12 | Pending |

**Coverage:**
- v1 requirements: 50 total
- Mapped to phases: 50
- Unmapped: 0 ✓

---
*Requirements defined: 2026-06-25*
*Last updated: 2026-06-25 after initial definition*
