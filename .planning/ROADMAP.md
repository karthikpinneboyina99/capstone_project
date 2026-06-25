# Roadmap: AI Trading Workstation

## Overview

This roadmap builds an AI-assisted paper-trading platform in 12 sequential phases, mirroring the dependency ordering established in `planning/plan.md`. The market data abstraction layer is already complete. Phases 1-3 lay the database and API foundation; Phases 4-6 build the ML and LLM decision pipeline; Phases 7-8 wire that pipeline into the backtester and live paper executor; Phase 9 surfaces everything in a React dashboard; and Phases 10-12 harden the stack with a test pass, containerized deployment, and demo-ready documentation. The central architectural invariant — that the backtester and live executor call the exact same `services/decision.py` function — runs through every phase from 4 onward.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Database and Models** - Define all SQLAlchemy ORM models and run the first Alembic migration
- [ ] **Phase 2: Historical Data Ingestion** - Backfill OHLCV, Alpaca live bars, and NewsAPI headlines into the database
- [ ] **Phase 3: Backend API Skeleton** - FastAPI application with all routers, Pydantic schemas, middleware, and logging
- [ ] **Phase 4: Feature Engineering** - Compute the full technical indicator set with a no-lookahead guarantee
- [ ] **Phase 5: ML Signal Model** - Train XGBoost with walk-forward validation and expose a versioned inference function
- [ ] **Phase 6: LLM Reasoning Layer** - Assemble context, call Cerebras, cache decisions, validate structured output
- [ ] **Phase 7: Backtesting Engine** - Day-by-day event-driven replay using the shared decision function, with metrics and sanity checks
- [ ] **Phase 8: Paper Trading Executor** - Alpaca paper order placement with risk checks, startup assertion, and daily scheduled job
- [ ] **Phase 9: Frontend Dashboard** - Five-page React dashboard wired to the live backend, including the Signals demo page
- [ ] **Phase 10: Testing Pass** - Full pytest and vitest coverage green across features, ML, LLM parsing, backtest math, risk checks, and API endpoints
- [ ] **Phase 11: Containerization and Deployment** - Docker Compose local stack, Render/Railway + Vercel deploy, GitHub Actions CI, production cron
- [ ] **Phase 12: Documentation and Demo Prep** - README, honest backtest write-up, and rehearsed 5-10 minute end-to-end demo script

## Phase Details

### Phase 1: Database and Models
**Goal**: The complete PostgreSQL schema is live — all nine tables modeled in SQLAlchemy, migrated, and queryable
**Depends on**: Nothing (market data layer already built; this phase creates the DB foundation all later phases write to)
**Requirements**: DATA-01, DATA-02
**Success Criteria** (what must be TRUE):
  1. `uvicorn app.main:app --reload` starts without errors and connects to Postgres
  2. All nine tables (instruments, price_bars, news_articles, ml_signals, llm_decisions, trades, positions, portfolio_snapshots, backtest_runs) exist in the database with correct foreign keys, indexes, and TimestampMixin columns
  3. The unique index on `llm_decisions(instrument_id, as_of_date, model_slug, prompt_version)` is present and enforces no duplicates
  4. `database/schema.sql` is auto-generated via `pg_dump --schema-only` and committed (not maintained manually)
**Plans**: TBD

### Phase 2: Historical Data Ingestion
**Goal**: The database is populated with 2-5 years of adjusted OHLCV bars, live-bar capability exists for the daily job, and news headlines are flowing into `news_articles`
**Depends on**: Phase 1
**Requirements**: DATA-03, DATA-04, DATA-05, DATA-06
**Success Criteria** (what must be TRUE):
  1. Running the yfinance loader backfills at least 2 years of adjusted-close daily bars for all watchlist symbols into `price_bars` (auto_adjust=True, no raw close)
  2. The watchlist (5-15 liquid large-cap symbols including AAPL, MSFT, NVDA, SPY, QQQ) is stored in the `instruments` table and all loaders operate on it
  3. The Alpaca live-bars loader pulls today's bars via `alpaca-py` and upserts them into `price_bars` without duplicates
  4. The NewsAPI loader ingests headlines per watchlist symbol into `news_articles` within the 100 req/day free-tier budget
**Plans**: TBD

### Phase 3: Backend API Skeleton
**Goal**: The FastAPI application exposes all planned endpoints with Pydantic schemas, structured error handling, and logging — ready for service layers to be plugged in
**Depends on**: Phase 1
**Requirements**: API-01, API-02, API-03
**Success Criteria** (what must be TRUE):
  1. `GET /instruments` returns the watchlist from the database; all eight router groups (instruments, price data, signals, decisions, trades, positions, portfolio, backtests) respond without 500 errors
  2. Every request and response body is validated by a Pydantic schema — no raw dict returns
  3. Invalid requests return structured error responses (not raw exception tracebacks); all requests are logged with method, path, status code, and latency
  4. `GET /stream/portfolio` SSE endpoint stub exists and maintains an open connection (even if it sends placeholder events until Phase 8 wires it fully)
**Plans**: TBD

### Phase 4: Feature Engineering
**Goal**: A pure feature-computation layer produces the full technical indicator set for any (symbol, as_of_date) using only data available as of that date
**Depends on**: Phase 1, Phase 2
**Requirements**: FEAT-01, FEAT-02, FEAT-03, FEAT-04
**Success Criteria** (what must be TRUE):
  1. Calling the feature function for a given (symbol, as_of_date) returns all required indicators: 1d/5d/20d returns, SMA(10/20/50), EMA(12/26), price-relative-to-MA, RSI(14), MACD line/signal/histogram, Bollinger Bands (20, 2σ: %B and bandwidth), 20d rolling volatility, volume z-score vs 20d lagged average, and day-of-week
  2. Calling the feature function with a past `as_of_date` never accesses bars with timestamp after that date — verified by a test that injects a future bar and confirms it does not appear in features
  3. Every indicator has a unit test comparing computed output against a hand-calculated expected value on a small fixture dataset; all tests pass
  4. Rows where any feature is NaN (first ~50 bars/symbol warmup) are dropped and forward-fill is never used — confirmed by tests
**Plans**: TBD

### Phase 5: ML Signal Model
**Goal**: An XGBoost regressor is trained with walk-forward validation, a versioned artifact is saved, and a shared inference function returns a signal score for any (symbol, as_of_date)
**Depends on**: Phase 4
**Requirements**: ML-01, ML-02, ML-03, ML-04
**Success Criteria** (what must be TRUE):
  1. `services/ml/train.py` completes a walk-forward training run using expanding-window time-series splits (never sklearn shuffle K-fold) and saves `backend/models/xgb_v1.json` plus a fitted scaler artifact
  2. `services/ml/predict.py` loads a versioned artifact and returns a normalized signal score (via z-score scaler) for (symbol, as_of_date) using only data available as of that date
  3. Out-of-sample validation metrics (MAE/RMSE or directional accuracy) are printed and committed to a results file — even if the model underperforms, they are documented honestly
  4. The inference function is importable and callable by both the backtester and live executor without modification
**Plans**: TBD

### Phase 6: LLM Reasoning Layer
**Goal**: For any (symbol, as_of_date), the system checks the decision cache, assembles a versioned context payload, calls Cerebras `gpt-oss-120b` if needed, validates the structured output, persists the full decision, and handles rate-limit retries and malformed responses gracefully
**Depends on**: Phase 5
**Requirements**: LLM-01, LLM-02, LLM-03, LLM-04, LLM-05, LLM-06
**Success Criteria** (what must be TRUE):
  1. A cache hit on `llm_decisions(instrument_id, as_of_date, model_slug, prompt_version)` returns the stored decision immediately — no Cerebras API call is made; confirmed by a test that pre-inserts a row and asserts the mock client is never called
  2. A cache miss assembles context (ML signal + top-3 features, 5-10 day price summary, 3-5 headlines with `published_at <= as_of_date`, current position and risk constraints) and calls `gpt-oss-120b` via the `openai` SDK pointed at `https://api.cerebras.ai/v1`; the response is validated by a Pydantic model with fields `{action, position_size_pct, confidence, rationale, risk_flags}`
  3. Every decision — including the full raw prompt and raw response JSON — is persisted to `llm_decisions`; a malformed LLM response is logged and raises a typed exception rather than silently producing a bad decision
  4. The LLM client wraps calls with `tenacity` exponential backoff (`min=4s, max=60s`) on 429 responses; a 429 in tests triggers the retry decorator without hitting the real API
  5. All parsing and validation logic is covered by unit tests that mock the OpenAI client — the real Cerebras API is never called in the test suite
**Plans**: TBD

### Phase 7: Backtesting Engine
**Goal**: A day-by-day event-driven replay over a configurable date range calls the shared decision function, simulates D+1 fills, computes all required metrics, passes the shuffle sanity check, and stores at least one full run with a buy-and-hold comparison
**Depends on**: Phase 6
**Requirements**: BACK-01, BACK-02, BACK-03, BACK-04, BACK-05, BACK-06
**Success Criteria** (what must be TRUE):
  1. The backtester replays a configurable date range day-by-day; fills are simulated at next trading day's D+1 open (never same-bar close); the final day of the range receives no fill
  2. `engine.py` imports and calls `services/decision.py` — the exact same function used by the live executor; no duplicate feature/signal/LLM logic exists anywhere in `backtesting/`
  3. After a full run, the engine reports: total return, CAGR, annualized Sharpe ratio (using daily portfolio returns), max drawdown, win rate, average win/loss, and number of trades
  4. A shuffle sanity check is available: re-running with randomized signals produces near-zero or negative performance, confirming no lookahead bias
  5. At least one full run is stored in `backtest_runs` with metrics compared against a SPY buy-and-hold baseline over the same period
  6. Sharpe ratio and max drawdown computations are unit-tested against hand-computed examples
**Plans**: TBD

### Phase 8: Paper Trading Executor
**Goal**: A scheduled daily job runs the complete decision pipeline per watchlist symbol, applies risk checks, places paper orders via Alpaca, and the SSE endpoint streams live portfolio updates to the frontend
**Depends on**: Phase 7
**Requirements**: TRADE-01, TRADE-02, TRADE-03, TRADE-04, TRADE-05, API-04
**Success Criteria** (what must be TRUE):
  1. `executor.py` asserts `ALPACA_BASE_URL == https://paper-api.alpaca.markets` at startup and raises an error (refuses to run) if the URL differs
  2. The daily job runs the same feature → ML signal → LLM decision pipeline as the backtester per watchlist symbol and submits paper orders via `alpaca-py`; trades appear in the Alpaca paper dashboard
  3. Risk checks are enforced: MAX_POSITION_PCT (10%), MAX_POSITIONS (8), DAILY_LOSS_LIMIT_PCT (3%) — all configurable via env vars; a position or daily-loss limit breach blocks the trade without crashing the job
  4. Risk checks are unit-tested independently with a mocked Alpaca API client
  5. The APScheduler daily job runs reliably for at least several consecutive trading days with logged decisions and trades visible in `llm_decisions` and `trades` tables
  6. `GET /stream/portfolio` SSE endpoint pushes live portfolio value and position updates to connected clients
**Plans**: TBD
**UI hint**: yes

### Phase 9: Frontend Dashboard
**Goal**: Five fully wired React pages — Dashboard, Signals, Trades, Backtests, Settings — display live data from the backend with no mock data remaining; the Signals page exposes the LLM rationale as the primary demo centerpiece
**Depends on**: Phase 8
**Requirements**: UI-01, UI-02, UI-03, UI-04, UI-05, UI-06, UI-07, UI-08, UI-09
**Success Criteria** (what must be TRUE):
  1. The Signals page shows today's ML signal score and LLM decision (action, confidence, expandable rationale text) per watchlist symbol — all data from the live backend; this page is the demo centerpiece
  2. The Dashboard page shows current portfolio value, today's P&L, an equity curve (recharts), and open positions table — all from the live backend
  3. The Trades page shows full paper trade history filterable by symbol and date; the Backtests page allows triggering a new run and displays equity curve, metrics table, and SPY comparison
  4. Every page handles loading, error, and empty states — not just the happy path; all pages carry a visible persistent disclaimer: "Paper trading only — not financial advice"
  5. A candlestick chart (`lightweight-charts`) is available for any selected symbol; the layout is responsive enough to demo on a laptop screen
**Plans**: TBD
**UI hint**: yes

### Phase 10: Testing Pass
**Goal**: pytest and npm test are both green; coverage spans features, ML inference, LLM parsing (mocked), backtest metrics, risk checks, key API endpoints, and the Signals and Dashboard frontend components
**Depends on**: Phase 9
**Requirements**: TEST-01, TEST-02, TEST-03
**Success Criteria** (what must be TRUE):
  1. `pytest` runs green with test coverage across: feature computation (hand-fixture values), ML inference (mocked model artifact), LLM response parsing (mocked OpenAI client, including malformed-response path), backtest metrics (Sharpe and max drawdown against hand examples), risk checks (mocked Alpaca), and key API endpoints (httpx TestClient)
  2. `npm test` (vitest) runs green with component tests covering at least the Signals and Dashboard pages
  3. Both `pytest` and `npm test` are clean before any phase is marked complete and remain clean after this phase
**Plans**: TBD

### Phase 11: Containerization and Deployment
**Goal**: The full stack runs locally via `docker-compose up`; backend and Postgres are deployed on Render or Railway, frontend on Vercel, GitHub Actions CI runs on every push, and the production daily job is configured
**Depends on**: Phase 10
**Requirements**: INFRA-01, INFRA-02, INFRA-03, INFRA-04
**Success Criteria** (what must be TRUE):
  1. `docker-compose up` from the repo root brings up backend, Postgres, and frontend as a unified local stack with no manual setup steps beyond copying `.env`
  2. The backend and Postgres are deployed and reachable at a public URL on Render or Railway; the frontend is deployed on Vercel; no secrets or `.env` files are in the repository
  3. The production daily job (Render Cron Job or scheduled GitHub Actions workflow) is configured and has run at least once successfully
  4. A GitHub Actions CI workflow runs `pytest` and frontend tests/build on every push to main and reports pass/fail status
**Plans**: TBD

### Phase 12: Documentation and Demo Prep
**Goal**: The README is current with setup instructions and screenshots; backtest results are documented honestly; a rehearsed 5-10 minute end-to-end demo script is ready to execute
**Depends on**: Phase 11
**Requirements**: DOC-01, DOC-02, DOC-03
**Success Criteria** (what must be TRUE):
  1. Root `README.md` contains: local setup instructions (clone → fill `.env` → `docker-compose up`), architecture summary with diagram, and at least one screenshot of the Signals page
  2. Backtest results are documented honestly — including underperformance vs SPY buy-and-hold if applicable — framed as analytical rigor rather than marketing
  3. A written 5-10 minute demo script covers: Signals page with LLM rationale visible → trigger a backtest run → show a paper trade end-to-end → run test suite and show green output
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Database and Models | 0/TBD | Not started | - |
| 2. Historical Data Ingestion | 0/TBD | Not started | - |
| 3. Backend API Skeleton | 0/TBD | Not started | - |
| 4. Feature Engineering | 0/TBD | Not started | - |
| 5. ML Signal Model | 0/TBD | Not started | - |
| 6. LLM Reasoning Layer | 0/TBD | Not started | - |
| 7. Backtesting Engine | 0/TBD | Not started | - |
| 8. Paper Trading Executor | 0/TBD | Not started | - |
| 9. Frontend Dashboard | 0/TBD | Not started | - |
| 10. Testing Pass | 0/TBD | Not started | - |
| 11. Containerization and Deployment | 0/TBD | Not started | - |
| 12. Documentation and Demo Prep | 0/TBD | Not started | - |
