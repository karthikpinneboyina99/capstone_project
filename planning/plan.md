# AI Trading Workstation — Capstone Build Plan

This is the single source of truth for the project. Claude Code reads this file every session (via the `@planning/plan.md` import in `CLAUDE.md`). Every phase below ends in a checklist — check items off as they're actually done (code written *and* tested), not when they're merely started.

**Working rule for every session:** scroll to "13. Build Phases," find the first unchecked `[ ]` item, and continue from there. Do not jump ahead to a later phase while an earlier phase still has unchecked boxes, unless explicitly told to.

---

## 1. What We're Building

An AI-assisted research and paper-trading platform for US stocks/ETFs. It:

1. Pulls historical and daily market data for a watchlist of symbols.
2. Engineers technical features and generates a quantitative ML signal per symbol per day.
3. Feeds that signal — plus recent price action and news headlines — to an LLM (`gpt-oss-120b` via Cerebras free tier), which reasons over all of it and outputs a structured trade decision with a plain-English rationale.
4. Backtests that combined ML + LLM strategy against historical data and reports performance metrics.
5. Runs the same decision pipeline live against Alpaca's **paper trading** account (fake money, real market data) on a schedule.
6. Displays everything — portfolio value, signals, rationale, trade history, backtest results — in a React dashboard.

### Explicitly out of scope

- No real-money / live brokerage execution. Paper trading only, everywhere, always.
- No multi-user auth system. Single operator (you).
- Not investment advice — the UI must say so. This is a portfolio/capstone project, not a product.

---

## 2. Success Criteria

The capstone is "done" when all of the following are true:

- [x] A documented ML pipeline turns OHLCV + technical indicators into a daily signal score for every symbol on the watchlist.
- [x] An LLM reasoning layer consumes that signal + context and returns a structured, explainable decision (buy/sell/hold, size, confidence, rationale).
- [x] A backtesting engine replays at least 2 years of history with no lookahead bias and reports CAGR, Sharpe ratio, max drawdown, win rate.
- [x] The same decision pipeline runs against Alpaca paper trading on a daily schedule and logs every decision and trade.
- [x] A React dashboard shows live portfolio state, today's signals with rationale, trade history, and backtest results.
- [x] Backend has an automated test suite (pytest) covering features, ML inference, LLM response parsing, backtest math, and risk checks.
- [ ] The whole stack runs locally via `docker-compose up` and is deployed somewhere reachable by URL.
- [ ] README + this plan are current and a 5-10 minute demo can be given end-to-end.

---

## 3. Architecture Overview

```
                         ┌─────────────────────┐
                         │   Market Data APIs   │  (yfinance, Alpaca Market Data)
                         │  News                │  (NewsAPI free tier)
                         └──────────┬───────────┘
                                    │ ingestion jobs
                                    ▼
                         ┌─────────────────────┐
                         │      PostgreSQL       │  price_bars, news_articles
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │ Feature Engineering   │  SMA/EMA/RSI/MACD/BB/volatility
                         └──────────┬───────────┘
                                    ▼
                         ┌─────────────────────┐
                         │   ML Signal Model     │  XGBoost (baseline) → signal score
                         └──────────┬───────────┘
                                    ▼
                         ┌─────────────────────┐
                         │   LLM Reasoning        │  signal + news
                         │  (Decision Engine)     │  → {action, size, confidence, why}
                         └──────────┬───────────┘
                          ┌─────────┴─────────┐
                          ▼                   ▼
                ┌──────────────────┐ ┌──────────────────────┐
                │ Backtesting Engine│ │ Paper Trading Executor│ → Alpaca Paper API
                │ (historical replay)│ │ (scheduled, live data)│
                └──────────────────┘ └──────────┬───────────┘
                                                  ▼
                                       ┌─────────────────────┐
                                       │     FastAPI Backend   │  REST + WebSocket
                                       └──────────┬───────────┘
                                                  ▼
                                       ┌─────────────────────┐
                                       │   React Dashboard      │
                                       └─────────────────────┘
```

The key design rule: **the backtester and the live paper-trading executor call the exact same decision function** (features → ML signal → LLM decision). If they diverge, the backtest stops meaning anything. Build the decision function once, as a pure function of (symbol, as_of_date, available_data), and call it from both places.

---

## 4. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Backend language/framework | Python 3.11+, FastAPI | Async, great for ML + API in one language |
| ORM / DB | SQLAlchemy + PostgreSQL | Mature, handles time-series well enough at this scale |
| Migrations | Alembic | Standard with SQLAlchemy |
| Market data (historical) | `yfinance` | Free, no key required, good enough for daily bars |
| Market data + execution (live) | `alpaca-py` (Alpaca's current SDK) | Free paper trading account, real-time data, order execution in one API |
| News (headlines) | NewsAPI free tier (100 req/day) | Adds real-world context for the LLM's reasoning; fundamentals ingestion is out of scope |
| Feature engineering | `pandas`, `numpy`, `ta` | Standard technical-indicator tooling |
| ML model | `scikit-learn` + `xgboost` (baseline); stretch: PyTorch LSTM | XGBoost on tabular technical features is a strong, fast baseline |
| LLM reasoning | **Cerebras** (`gpt-oss-120b`, free tier), via the OpenAI-compatible API (`openai` Python SDK pointed at `https://api.cerebras.ai/v1`) | $0 cost, ~3000 tok/s inference, ~30 RPM / 60K tokens/min free tier — decision cache is mandatory for backtesting |
| Scheduling | `APScheduler` (or cron calling an endpoint) | Daily ingestion + signal + decision job |
| Frontend | React + Vite + TypeScript | Fast dev loop, typed |
| Styling | Tailwind CSS | Fast to build a clean dashboard |
| Charts | `lightweight-charts` (candlesticks) + `recharts` (equity curve, bar charts) | Purpose-built for financial charting |
| Data fetching (frontend) | `@tanstack/react-query` + `axios` + native `EventSource` (SSE) | React Query for REST; SSE for real-time server→client push (portfolio updates, live signals) |
| Testing (backend) | `pytest`, `pytest-asyncio`, `httpx` | Standard FastAPI testing stack |
| Testing (frontend) | `vitest`, `@testing-library/react` | Standard Vite testing stack |
| Containerization | Docker + docker-compose | Reproducible local + deploy |
| Deployment | Render or Railway (backend + Postgres), Vercel (frontend) | Free/cheap tiers, simple deploys |
| CI | GitHub Actions | Run tests on every push |

---

## 5. Prerequisites (do this before any code)

1. **Install locally:** Python 3.11+, Node.js 20+, Git, Docker Desktop (optional but recommended), PostgreSQL (or just use Docker for it — no local install needed).
2. **Create accounts and collect API keys:**
   - Alpaca (https://alpaca.markets) → sign up → enable **Paper Trading** → generate API Key ID + Secret Key. Note the paper base URL (`https://paper-api.alpaca.markets`).
   - Cerebras (https://cloud.cerebras.ai) → create an account → generate an API key. The LLM reasoning layer calls `gpt-oss-120b` through Cerebras' OpenAI-compatible API — zero cost on the free tier, rate-limited to 30 RPM and 60K tokens/minute. No OpenRouter account needed.
   - NewsAPI (https://newsapi.org) → sign up → generate an API key. The news loader uses this for daily headlines per symbol (100 req/day on the free tier is sufficient). Financial Modeling Prep is not needed — fundamentals ingestion is out of scope.
3. **Git/GitHub:** create a repo, push this scaffold, commit early and often. Never commit `.env`.
4. **Claude Code:** confirm it's installed and authenticated, and that opening this project folder loads `CLAUDE.md` automatically (check the session start message references this plan).

Definition of done for this section:

- [ ] Alpaca paper account created, keys saved (not committed)
- [ ] Cerebras API key created, saved (not committed)
- [ ] NewsAPI key created, saved (not committed)
- [ ] Local Python/Node/Docker installed and verified (`python3 --version`, `node --version`, `docker --version`)
- [ ] GitHub repo created and this scaffold pushed

---

## 6. Final Directory Structure

```
AI-TRADING-WORKSTATION/
├── .claude                     # pointer file → this plan
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/                # settings, security, logging
│   │   ├── api/                 # FastAPI routers
│   │   ├── models/               # SQLAlchemy models
│   │   ├── schemas/               # Pydantic schemas
│   │   ├── services/
│   │   │   ├── data_ingestion/
│   │   │   ├── features/
│   │   │   ├── ml/
│   │   │   ├── llm_reasoning/
│   │   │   ├── backtesting/
│   │   │   └── trading/
│   │   └── db/
│   ├── models/                  # ML artifacts (xgb_v1.json, scaler_v1.pkl) — git-ignored
│   ├── requirements.txt
│   └── Dockerfile
├── database/
│   ├── migrations/
│   └── schema.sql
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── hooks/
│   │   └── api/
│   ├── package.json
│   └── Dockerfile
├── planning/
│   └── plan.md                 # this file
├── tests/
│   ├── backend/
│   └── frontend/
├── .env.example
├── .gitignore
├── CLAUDE.md
├── docker-compose.yml           # added in Phase 11
├── LICENSE
└── README.md
```

---

## 7. Database Schema

Build these as SQLAlchemy models in `backend/app/models/`, then generate the Alembic migration. Use a `TimestampMixin` (one-line mixin adding `created_at TIMESTAMPTZ DEFAULT now()`) on tables that need audit trails.

**instruments** — symbol, name, sector, asset_class, is_active

**price_bars** — instrument_id (FK), timestamp, open, high, low, close, volume, timeframe (e.g. `1d`). Unique on (instrument_id, timestamp, timeframe). Always store adjusted close values (splits + dividends).

**news_articles** — instrument_id (FK, nullable for market-wide news), published_at, headline, summary, source, url, sentiment_score (nullable), created_at

**ml_signals** — instrument_id (FK), as_of_date, model_version, signal_score (-1 to 1), features_used (JSON snapshot for auditability), created_at

**llm_decisions** — instrument_id (FK), as_of_date, ml_signal_id (FK), action (buy/sell/hold), position_size_pct, confidence, rationale (text), risk_flags (JSON array of strings), raw_response (JSON), prompt_version, model_slug (e.g. `gpt-oss-120b`), created_at. **Unique on (instrument_id, as_of_date, model_slug, prompt_version)** — this index is the decision cache key; always check for an existing row before calling the LLM.

**trades** — instrument_id (FK), decision_id (FK, nullable), side, quantity, price, executed_at, mode (backtest/paper), alpaca_order_id (nullable), created_at

**positions** — instrument_id (FK), quantity, avg_entry_price, mode (backtest/paper), backtest_run_id (FK, nullable — NULL for paper-mode rows), updated_at. **Unique on (instrument_id, mode, backtest_run_id)** — use a partial unique index in Postgres to handle the nullable `backtest_run_id` for paper-mode rows correctly.

**portfolio_snapshots** — as_of_date, mode (backtest/paper), cash, equity, total_value, backtest_run_id (FK, nullable — NULL for paper-mode rows). **Unique on (as_of_date, mode, backtest_run_id)** — prevents duplicate snapshot rows if the daily job restarts and runs twice on the same date.

**backtest_runs** — started_at, finished_at, date_range_start, date_range_end, strategy_version, params (JSON), result metrics (JSON: CAGR, Sharpe, max_drawdown, win_rate, num_trades), created_at

> `fundamentals` table is out of scope — the LLM context uses price action and news only.

Definition of done:

- [x] All tables modeled in SQLAlchemy with correct FKs and indexes (on `(instrument_id, timestamp)` for price_bars; unique on `(instrument_id, as_of_date, model_slug, prompt_version)` for llm_decisions)
- [x] Alembic initialized, first migration generated and applied
- [x] `database/schema.sql` auto-generated from Alembic via `pg_dump --schema-only` — not maintained manually

---

## 8. Feature Engineering & ML Signal Model

**Features per symbol per day** (computed from `price_bars`, no future data):

- Returns: 1d, 5d, 20d
- Moving averages: SMA(10/20/50), EMA(12/26), and price relative to each
- RSI(14)
- MACD line, signal line, histogram
- Bollinger Bands (20, 2σ): %B and bandwidth
- Rolling volatility (20d std of returns)
- Volume z-score vs 20d average (use a strictly lagged rolling mean/std — `df['volume'].shift(1).rolling(20).mean()` — so day D's own volume is not included in its own denominator)
- Day-of-week (categorical, optional)

**Label** (for training only): forward 5-day return (5 trading days, fixed — do not change after the first training run). Regression on forward return rather than binary classification; it carries more information and makes the signal score proportional to expected move magnitude.

**Model**: start with `XGBRegressor` predicting forward return; convert to a signal score by normalizing predicted return via a z-score scaler. Stretch goal: add an LSTM/sequence model and compare.

**Validation — critical**: use walk-forward (expanding window) time-series splits, never `sklearn`'s default shuffle-based K-fold. Train on data up to time T, validate on T+1..T+k, roll forward. Report out-of-sample metrics only (MAE/RMSE for regression, or directional accuracy).

**No lookahead bias rule**: when generating a signal for date D, only use bars with timestamp ≤ D (end of day D, after market close, using that day's adjusted close).

**Adjusted prices rule**: always use split- and dividend-adjusted close prices (`Adj Close` from yfinance, via `auto_adjust=True`). Raw close produces phantom signals around split and dividend dates.

**NaN handling rule**: drop any row where any feature value is NaN (the first ~50 bars per symbol will have NaN during indicator warmup). Never forward-fill features — that introduces subtle lookahead.

**Normalization rule**: the z-score scaler on predicted returns must be fitted on training data only within each walk-forward window, then saved alongside the XGBoost model artifact. Never fit the scaler across the full dataset before splitting.

Definition of done:

- [x] `services/features/` computes the full feature set from `price_bars`, covered by unit tests with known inputs/outputs
- [x] `services/ml/train.py` trains XGBoost with walk-forward validation and saves a versioned model artifact
- [x] `services/ml/predict.py` loads a model version and returns a signal score for (symbol, as_of_date) using only data available as of that date
- [x] Out-of-sample validation metrics documented (even if mediocre — document honestly, this is a learning exercise, not a magic-alpha claim)

---

## 9. LLM Reasoning Layer (Decision Engine)

This is the part that makes it an "AI" trading workstation rather than a plain quant bot.

**Inputs assembled per (symbol, as_of_date):**

- ML signal score + a one-line description of what drove it (e.g., top 3 contributing features)
- Recent price action summary (last 5-10 days, plain text: "up 4.2% over 5 days, RSI 68, near upper Bollinger Band")
- Latest 3-5 news headlines for the symbol, with dates (query must filter `published_at <= as_of_date` — never use the current timestamp as the upper bound, or the backtest will see future news)
- Current position (if any) and portfolio risk constraints (max position size, available cash)

**API access:** call `gpt-oss-120b` through **Cerebras** (`https://api.cerebras.ai/v1`) using the `openai` Python SDK — Cerebras is OpenAI-API-compatible, so set `base_url` to the Cerebras endpoint, `api_key` to `LLM_API_KEY`, and `model` to the value from `LLM_MODEL`. The codebase only needs the `openai` package.

**Prompt design:**

- System prompt establishes role, constraints (paper trading only, risk limits, must use the provided data only, must output valid structured JSON), and the exact output schema.
- Use the model's tool-use / structured-output capability so the response is parseable JSON, not free text to regex out. (`gpt-oss-120b` on Cerebras supports native function calling and structured outputs.) Output schema: `{"action": "buy"|"sell"|"hold", "position_size_pct": float, "confidence": float (0-1), "rationale": string, "risk_flags": [string]}`.
- Keep temperature low (near 0) for consistency.
- Log the full prompt and raw response for every decision (`llm_decisions.raw_response`) — required for both debugging and the capstone write-up.

**LLM authority rule**: the LLM's `action` field is the final decision — it can override the ML signal. The ML signal score is one strong input in the prompt, not a binding constraint. This is the feature: when the LLM overrides a strong buy signal due to negative news or risk flags, that override and its rationale are the story you demo.

**Versioning**: `model_version` in `ml_signals` = XGBoost artifact filename without extension (e.g., `xgb_v1`). `prompt_version` in `llm_decisions` = integer constant `PROMPT_VERSION` defined in the codebase; increment it manually whenever the prompt template changes.

**Cost/latency note for backtesting:** Cerebras' free tier (~30 RPM / 60K tokens/min) can't sustain a multi-year, multi-symbol backtest calling the API on every day. Mitigations:

- Run the full multi-year backtest on the ML-only signal as the primary backtest, and run the LLM-augmented layer on a representative sample (e.g., last 6-12 months, or one trading day per week) — clearly label which backtest used which mode.
- Before every LLM call, check the `llm_decisions` table for a row matching (instrument_id, as_of_date, model_slug, prompt_version). The unique index on those four columns enforces no duplicates; re-running a backtest never re-calls the API for dates already processed.
- Wrap the LLM client with exponential backoff and jitter on 429 responses (`tenacity` integrates cleanly: `@retry(wait=wait_exponential(min=4, max=60), retry=retry_if_exception_type(RateLimitError))`). Without this, burst calls during a backtest will crash with unhandled exceptions.
- For the demo: pre-generate all decisions the evening before by running the pipeline on that day's data. The Signals page reads from the DB; the live API is never called during the demo.

Definition of done:

- [x] `services/llm_reasoning/` builds the context payload, calls the LLM (Cerebras, `gpt-oss-120b`) with a versioned prompt, and parses a validated structured response (Pydantic model validates the JSON)
- [x] Decisions and raw responses are persisted to `llm_decisions`
- [x] Unit tests mock the OpenAI client and verify parsing/validation logic, including malformed-response handling
- [x] A documented decision on the cost/latency mitigation chosen for backtesting

---

## 10. Backtesting Engine

Build a straightforward event-driven (day-by-day) backtester — don't reach for a heavyweight library; a custom one demonstrates more understanding for a capstone and keeps you in full control of the decision-engine integration.

**Loop, per trading day D in the backtest range:**

1. For each symbol on the watchlist: compute features using data ≤ D, get ML signal, call the decision engine (per the cost mitigation above), get a decision.
2. Apply risk checks (position size caps, max number of concurrent positions, available cash).
3. Simulate fills at next trading day's open (D+1 open). You cannot trade at the same bar's close you just observed. Edge case: the final day of the backtest range has no D+1 open and receives no fill; exclude it from return calculations.
4. Update simulated positions, cash, and record a `portfolio_snapshots` row.

**Metrics to compute at the end:**

- Total return, CAGR
- Sharpe ratio (annualized, using daily portfolio returns)
- Max drawdown
- Win rate and average win/loss
- Number of trades, turnover

**Sanity checks before trusting any result:**

- Compare against a buy-and-hold SPY baseline over the same period.
- Re-run with signals shuffled/randomized — performance should collapse to noise. If your "strategy" still looks good with randomized signals, something is leaking future information.

Definition of done:

- [x] `services/backtesting/engine.py` runs a full historical replay with no lookahead bias (verified by the shuffle sanity check)
- [x] Metrics module unit-tested against hand-computed examples (especially Sharpe and max drawdown)
- [x] At least one full backtest run stored in `backtest_runs` with results, comparable against a buy-and-hold baseline
- [x] Results are honestly reported in the README/demo even if the strategy underperforms buy-and-hold — the capstone is evaluated on rigor, not on beating the market

---

## 11. Paper Trading Execution

**Daily scheduled job** (APScheduler or cron hitting a `/jobs/run-daily` endpoint), timed to run shortly after market close or before next open:

1. Ingest the latest day's bars and news headlines for the watchlist.
2. For each symbol: run the exact same feature → ML signal → LLM decision pipeline used in the backtester.
3. Apply the same risk checks.
4. If action is buy/sell and passes risk checks, submit an order via `alpaca-py`'s trading client (paper endpoint only — verify `ALPACA_BASE_URL` points at `paper-api.alpaca.markets` and assert this at startup, refusing to run if it doesn't).
5. Log the decision and resulting trade; update `positions` and `portfolio_snapshots`.

**Risk management rules (env-var defaults, not optional):**

All thresholds are environment variables added to `.env.example` with these fixed defaults:

- `MAX_POSITION_PCT=0.10` — max 10% of portfolio per symbol ($10,000/position at Alpaca's default $100,000 paper balance).
- `MAX_POSITIONS=8` — max 8 concurrent open positions across the watchlist.
- `DAILY_LOSS_LIMIT_PCT=0.03` — if the day's mark-to-market loss exceeds 3% of portfolio ($3,000 on a $100k account), skip all new buys for the rest of the trading day.
- Always use Alpaca's paper endpoint; startup assertion throws if `ALPACA_BASE_URL` is not `https://paper-api.alpaca.markets`.

Definition of done:

- [x] `services/trading/executor.py` places paper orders through `alpaca-py`, with the paper-endpoint assertion in place
- [x] Risk checks are enforced and unit-tested independent of the live API (mocked)
- [ ] Scheduled job runs reliably for at least several consecutive trading days with logged decisions and trades
- [ ] Manual verification: trades appear correctly in the Alpaca paper dashboard

---

## 12. Frontend Dashboard

**Pages:**

- **Dashboard** — portfolio value, today's P&L, equity curve chart, open positions table
- **Signals** — today's ML signal + LLM decision per watchlist symbol, with the rationale text visible (this is the "show your AI" page)
- **Trades** — full trade history (paper), filterable by symbol/date
- **Backtests** — trigger a backtest run (date range, params), view results: equity curve, metrics table, comparison vs buy-and-hold
- **Settings** — watchlist management, risk parameter display (read-only is fine for a capstone)

**Key components:** candlestick chart (`lightweight-charts`) for a selected symbol, equity-curve line chart (`recharts`), signal/decision card (signal score, action, confidence, expandable rationale), trades data table.

Definition of done:

- [x] All five pages built and wired to the FastAPI backend (no mock data left in by demo time)
- [x] Loading/error/empty states handled, not just the happy path
- [x] Responsive enough to demo on a laptop screen
- [x] A visible, persistent disclaimer: "Paper trading only — not financial advice"

---

## 13. Build Phases (Step-by-Step, In Order)

Each phase lists concrete steps. Where useful, a literal prompt you can paste into Claude Code is included in quotes — adapt as needed, but keep the intent.

### Phase 0 — Environment Setup

- [x] `git init` (if not already), connect to GitHub remote
- [x] Create Python virtual environment in `backend/`: `python3 -m venv venv && source venv/bin/activate`
- [x] `pip install fastapi uvicorn[standard] sqlalchemy psycopg2-binary alembic pydantic pydantic-settings python-dotenv yfinance alpaca-py pandas numpy scikit-learn xgboost ta openai apscheduler pytest pytest-asyncio httpx`, then freeze: `pip freeze > backend/requirements.txt`
- [x] Scaffold frontend: `npm create vite@latest frontend -- --template react-ts`, then `cd frontend && npm install axios @tanstack/react-query recharts lightweight-charts -D tailwindcss postcss autoprefixer vitest @testing-library/react`
- [x] Fill in real values in a local `.env` (copied from `.env.example`, never committed)
- [x] Confirm Postgres is reachable (local install or `docker run postgres` for now; full docker-compose comes in Phase 11)
- Prompt: *"Read planning/plan.md sections 4-6. Set up the backend FastAPI skeleton (main.py, core/config.py reading from .env, db/session.py connecting to Postgres) and confirm `uvicorn app.main:app --reload` starts cleanly."*

### Phase 1 — Database & Models

- [x] Implement all tables from section 7 as SQLAlchemy models (including `TimestampMixin`, `backtest_run_id` FKs on positions/portfolio_snapshots, and `risk_flags` on llm_decisions)
- [x] Set up Alembic, generate and run the first migration
- [x] Auto-generate `database/schema.sql` via `pg_dump --schema-only` after migration runs — do not maintain it manually

### Phase 2 — Historical Data Ingestion

- [x] Build `services/data_ingestion/yfinance_loader.py`: pull daily OHLCV for the watchlist, backfill 2-5 years, upsert into `price_bars` using `auto_adjust=True` (adjusted close only)
- [x] Build `services/data_ingestion/alpaca_loader.py`: pull recent/live bars via `alpaca-py` for the daily job
- [x] Build `services/data_ingestion/news_loader.py`: pull latest headlines per symbol via NewsAPI, upsert into `news_articles`; fundamentals ingestion is out of scope
- [x] Define the watchlist (start small: 5-15 liquid large-cap symbols, e.g., AAPL, MSFT, NVDA, SPY, QQQ — easy to extend later)

### Phase 3 — Backend API Skeleton

- [x] Routers for: instruments/watchlist, price data, signals, decisions, trades, positions, portfolio, backtests; add a `GET /stream/portfolio` SSE endpoint stub (wire it fully in Phase 8)
- [x] Pydantic schemas mirroring the DB models for clean request/response typing
- [x] Basic error handling and logging middleware
- [x] Note: Phase 3 can only begin after Phase 1 models are finalized — Pydantic schemas must match the SQLAlchemy models

### Phase 4 — Feature Engineering

- [x] Implement the full feature set from section 8 as pure functions over a price DataFrame
- [x] Unit test every feature against hand-computed expected values on a small fixture dataset

### Phase 5 — ML Signal Model

- [x] Build the training pipeline with walk-forward validation
- [x] Save versioned model artifacts (e.g., `models/xgb_v1.json` + metadata)
- [x] Build the inference function used by both backtester and live job
- [x] Document out-of-sample validation results

### Phase 6 — LLM Reasoning Layer

- [x] Build context assembly, prompt template (versioned), and structured-output call to the LLM via Cerebras
- [x] Validate responses against a Pydantic schema; handle and log malformed responses gracefully
- [x] Persist decisions; mock-based unit tests for the parsing/validation logic
- Prompt: *"Implement services/llm_reasoning/decision_engine.py per plan.md section 9. Use the openai Python SDK pointed at Cerebras (base_url=https://api.cerebras.ai/v1, api_key from LLM_API_KEY env var, model from LLM_MODEL env var, default gpt-oss-120b), structured output, and a Pydantic model to validate the JSON response. Mock the OpenAI client in tests — do not call the real API in the test suite."*

### Phase 7 — Backtesting Engine

- [x] Implement the day-by-day replay loop and fill simulation
- [x] Implement and unit-test all metrics (CAGR, Sharpe, max drawdown, win rate)
- [x] Run the shuffle sanity check and the buy-and-hold comparison
- [x] Store at least one full run in `backtest_runs`

### Phase 8 — Paper Trading Executor

- [x] Implement order placement via `alpaca-py` with the paper-endpoint startup assertion
- [x] Implement and unit-test risk checks independent of the live API
- [x] Wire the daily scheduled job (APScheduler in-process, or an endpoint triggered by cron/GitHub Actions schedule)
- [ ] Let it run for several consecutive trading days before the demo; verify against the Alpaca paper dashboard

### Phase 9 — Frontend Dashboard

- [x] Build pages and components per section 12
- [x] Wire to real backend endpoints (no leftover mock data)
- [x] Add the paper-trading/not-financial-advice disclaimer

### Phase 10 — Testing Pass

- [x] Confirm coverage on: features, ML inference, LLM response parsing (mocked), backtest metrics, risk checks, key API endpoints (httpx TestClient)
- [x] Add frontend component tests for at least the Signals and Dashboard pages
- [x] `pytest` and `npm test` both green before moving on

### Phase 11 — Containerization & Deployment

- [x] Write `backend/Dockerfile`, `frontend/Dockerfile`, root `docker-compose.yml` (backend + Postgres + frontend)
- [ ] Confirm `docker-compose up` brings up the full stack locally
- [ ] Deploy backend + Postgres to Render or Railway; deploy frontend to Vercel; set environment variables/secrets on each platform (never in the repo)
- [ ] Set up the daily job in production (Render Cron Job, or a scheduled GitHub Actions workflow hitting the deployed endpoint)
- [x] Add a GitHub Actions workflow running `pytest` (and frontend tests/build) on every push

### Phase 12 — Documentation & Demo Prep

- [x] Update root `README.md` with setup instructions, architecture summary, and screenshots
- [ ] Write up backtest results honestly (including underperformance vs buy-and-hold, if applicable) — this is what shows analytical maturity to evaluators
- [ ] Prepare a 5-10 minute demo script: show the Signals page with the LLM's rationale, show a backtest run, show a live paper trade end-to-end, show test suite passing

---

## 14. Suggested Timeline (8 weeks, adjust freely)

| Week | Phases |
|---|---|
| 1 | 0, 1, 2 — environment, schema, data ingestion |
| 2 | 3, 4 — API skeleton, feature engineering |
| 3 | 5 — ML signal model + validation |
| 4 | 6 — LLM reasoning layer |
| 5 | 7 — backtesting engine + sanity checks |
| 6 | 8 — paper trading executor + scheduled job running daily |
| 7 | 9, 10 — frontend dashboard + test pass |
| 8 | 11, 12 — deployment, docs, demo prep |

---

## 15. Security & Compliance Notes

- `.env` is git-ignored; only `.env.example` (with placeholder values) is committed.
- Verify at startup that the Alpaca base URL is the paper endpoint — refuse to start otherwise.
- No code path should be able to place a live order; don't even build the live-trading client class, to remove the temptation/risk entirely.
- The UI carries a persistent "paper trading only — not financial advice" disclaimer.
- Rotate any API key that's ever accidentally committed, even to a private repo.

---

## 16. How to Resume Work With Claude Code

At the start of any session: *"Read planning/plan.md. Tell me the current phase based on which checkboxes are unchecked, and let's continue from there."* After finishing a checklist item, ask Claude Code to tick the corresponding box in this file as part of the same change — keep this document and the actual codebase in sync.

---

## 17. Disclaimer

This project is for educational/capstone purposes only. It trades exclusively in a simulated paper account. Nothing it produces — signals, the LLM's rationale, or backtest results — is financial advice or a recommendation to trade real money.

---

## 18. Key Design Decisions

A record of choices made during planning. Consult before asking "why does the code do X?"

| # | Decision | Choice | Rationale |
|---|---|---|---|
| D1 | LLM model | `gpt-oss-120b` via Cerebras | Free tier, ~3000 tok/s, OpenAI-compatible — no extra SDK needed |
| D2 | Forward-return label N | 5 trading days (fixed) | Best signal/noise ratio at daily-bar resolution; more training samples than 20d, meaningfully less noise than 1d |
| D3 | Backtest fill price | Next-day open (D+1) | Can't trade at same-bar close; next open is the realistic execution price and avoids same-bar lookahead |
| D4 | LLM authority | LLM is final authority | The LLM can override the ML signal; ML score is one strong input, not a binding constraint. Core demo narrative: "the AI overrode the quant signal because of this news headline" |
| D5 | News/fundamentals scope | News IN (`news_articles` table + NewsAPI loader), fundamentals OUT | News gives the LLM something to reason over; fundamentals are quarterly, add schema complexity, and are marginal for a daily-signal system |
| D6 | Max position size | 10% per symbol (`MAX_POSITION_PCT=0.10`) | $10k/position on $100k paper balance — standard allocation cap |
| D7 | Max concurrent positions | 8 (`MAX_POSITIONS=8`) | Diversified enough across a 10-15 symbol watchlist; small enough to stay in cash when signals are weak |
| D8 | Daily loss circuit breaker | 3% of portfolio (`DAILY_LOSS_LIMIT_PCT=0.03`) | $3k loss on $100k pauses new buys for the day — visible, testable risk guard |
| D9 | Decision cache | `llm_decisions` table, unique index on (instrument_id, as_of_date, model_slug, prompt_version) | Cache-before-call on every LLM request; re-running a backtest never re-calls the API |
| D10 | Demo rate-limit contingency | Pre-generate decisions the evening before the demo | Signals page reads from DB; live API never touched during demo, eliminating rate-limit risk |
| D11 | NaN handling | Drop rows with any NaN (first ~50 bars/symbol = warmup) | Safest approach; forward-fill introduces lookahead |
| D12 | Signal normalization | Z-score scaler fitted on training data per walk-forward window, saved with model artifact | Prevents leaking future distribution info into earlier folds |
| D13 | `model_version` format | Artifact filename without extension (e.g., `xgb_v1`) | Human-readable, directly tied to the saved file |
| D14 | `prompt_version` format | Integer constant `PROMPT_VERSION` in codebase, incremented manually | Simple, auditable; queries like "all decisions with prompt v2" are reliable |
| D15 | Daily job trigger | GitHub Actions schedule in production; APScheduler for local dev | Actions schedule is observable and restartable independently of the API server |
| D16 | Frontend build order | Signals → Dashboard → Trades → Backtests → Settings | Signals is the demo money shot; Backtests and Settings can be stubs if time runs short |
| D17 | Adjusted prices | `Adj Close` from yfinance (`auto_adjust=True`) everywhere | Raw close produces phantom signals around split and dividend dates |
| D18 | Partial fills | Treat all fills as complete; document the assumption | Alpaca paper fills are always immediate and full for liquid large-caps; handling partials adds complexity with no demo value |
| D19 | Demo audience | Technical evaluators (ML rigor and code quality) | Polish test coverage, validation metrics, and the LLM override story first; UI polish is secondary |