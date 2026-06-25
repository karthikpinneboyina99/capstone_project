<!-- refreshed: 2026-06-25 -->
# Architecture

**Analysis Date:** 2026-06-25

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────┐
│              External Market & LLM APIs                              │
│  Polygon/Massive REST  │  Cerebras LLM API  │  Alpaca Paper API     │
│  (MASSIVE_API_KEY)     │  (LLM_API_KEY)     │  (ALPACA_*)           │
└──────────┬─────────────┴────────┬────────────┴──────────────────────┘
           │                      │                         ▲
           ▼                      ▼                         │ orders
┌──────────────────────────────────────────────────────────────────────┐
│                    FastAPI Backend (planned)                          │
│  backend/app/                                                        │
│  ┌──────────────┐  ┌──────────────────┐  ┌──────────────────────┐   │
│  │ data_ingestion│  │ features/ + ml/  │  │ llm_reasoning/       │   │
│  │ (BUILT)       │  │ (planned)        │  │ (planned)            │   │
│  └──────┬───────┘  └──────┬───────────┘  └──────────┬───────────┘   │
│         │                 │                          │               │
│         ▼                 ▼                          ▼               │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │              backtesting/     +     trading/                  │    │
│  │              (planned)              (planned)                 │    │
│  └──────────────────────────────────────────────────────────────┘    │
│         │                                                             │
│         ▼                                                             │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │              api/routers/  (REST + WebSocket/SSE)             │    │
│  │              (planned)                                        │    │
│  └──────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────┬──────────────────────────────┘
                                       │ HTTP / SSE
                                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    React Dashboard  (frontend/)                       │
│                    dist/ (built); src/ (planned)                      │
└──────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    PostgreSQL / TimescaleDB                           │
│  price_bars  instruments  news_articles  ml_signals  llm_decisions   │
│  trades  positions  portfolio_snapshots  backtest_runs               │
└──────────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| MarketDataProvider ABC | Unified interface contract for all market data consumers | `backend/app/services/data_ingestion/market_interface.py` |
| create_provider() | Factory — picks MassiveProvider or SimulatorProvider based on env | `backend/app/services/data_ingestion/market_interface.py` |
| MassiveProvider | Live OHLCV from Polygon/Massive REST API with backoff | `backend/app/services/data_ingestion/massive_provider.py` |
| SimulatorProvider | Thin wrapper over MarketSimulator satisfying the ABC | `backend/app/services/data_ingestion/simulator_provider.py` |
| MarketSimulator | DB replay (price_bars) + GBM synthetic fallback | `backend/app/services/data_ingestion/market_simulator.py` |
| features/ | Technical indicator feature engineering (SMA/EMA/RSI/MACD/BB) | `backend/app/services/features/` (planned) |
| ml/ | XGBoost signal model — train + predict | `backend/app/services/ml/` (planned) |
| llm_reasoning/ | Cerebras LLM decision engine — prompt + parse + persist | `backend/app/services/llm_reasoning/` (planned) |
| backtesting/ | Event-driven historical replay engine | `backend/app/services/backtesting/` (planned) |
| trading/ | Paper trade executor against Alpaca paper API | `backend/app/services/trading/` (planned) |
| api/routers/ | FastAPI route handlers (REST + SSE) | `backend/app/api/routers/` (planned) |
| core/ | Settings, config, logging | `backend/app/core/` (planned) |
| db/ | SQLAlchemy session, connection pool | `backend/app/db/` (planned) |
| models/ | SQLAlchemy ORM table definitions | `backend/app/models/` (planned) |
| schemas/ | Pydantic request/response schemas | `backend/app/schemas/` (planned) |
| React dashboard | Portfolio, signals, trades, backtest, settings pages | `frontend/` (built as dist only) |
| market_data_demo.py | Standalone terminal demo of market data layer | `market_data_demo.py` |

## Pattern Overview

**Overall:** Layered service architecture with a Provider Pattern for market data and a shared decision function contract

**Key Characteristics:**
- All market data consumers call `create_provider()` — never import a concrete provider directly
- The backtester and live executor MUST call the exact same `features → ML signal → LLM decision` function — divergence invalidates the backtest
- LLM decisions are cached in the `llm_decisions` DB table (unique key: `instrument_id + as_of_date + model_slug + prompt_version`) — never re-call the API for a cached row
- Paper trading only: startup assertion checks `ALPACA_BASE_URL == https://paper-api.alpaca.markets`
- Simulation fallback: when `MASSIVE_API_KEY` is absent, data flows through GBM synthetic generator — CI/tests never need external API access

## Layers

**Data Ingestion:**
- Purpose: Supply OHLCV bars and quotes to all upstream consumers
- Location: `backend/app/services/data_ingestion/`
- Contains: ABC (`market_interface.py`), two concrete providers, one simulator
- Depends on: PostgreSQL `price_bars` table (optional, for DB replay), Massive/Polygon API (optional)
- Used by: Feature engineering, backtesting engine, live trading executor

**Feature Engineering (planned):**
- Purpose: Compute SMA/EMA/RSI/MACD/Bollinger Bands/volatility/volume z-scores per symbol per day
- Location: `backend/app/services/features/`
- Contains: Feature computation functions (no lookahead — only bars ≤ as_of_date)
- Depends on: data_ingestion layer
- Used by: ml/ train and predict, backtesting engine, live executor

**ML Signal Layer (planned):**
- Purpose: XGBoost regressor predicts 5-day forward return; normalized to signal score [-1, 1]
- Location: `backend/app/services/ml/`
- Contains: `train.py` (walk-forward validation), `predict.py` (load artifact, score single day)
- Depends on: features/, price_bars DB table
- Used by: backtesting engine, live executor

**LLM Reasoning / Decision Engine (planned):**
- Purpose: Convert (ML signal, price summary, news, position state) → structured trade decision
- Location: `backend/app/services/llm_reasoning/`
- Contains: Prompt builder, Cerebras API client wrapper, Pydantic response validator, DB cache check
- Depends on: ml/, news_articles DB table, llm_decisions DB table
- Used by: backtesting engine, live executor

**Backtesting Engine (planned):**
- Purpose: Day-by-day event-driven historical replay; fills simulated at D+1 open
- Location: `backend/app/services/backtesting/`
- Contains: `engine.py`, metrics module (CAGR, Sharpe, max drawdown, win rate)
- Depends on: data_ingestion, features, ml, llm_reasoning layers
- Used by: API router (triggered via POST), CLI

**Paper Trading Executor (planned):**
- Purpose: Run daily decision pipeline and place paper orders via Alpaca
- Location: `backend/app/services/trading/`
- Contains: `executor.py`, risk check module
- Depends on: data_ingestion, features, ml, llm_reasoning layers, `alpaca-py`
- Used by: APScheduler job or `/jobs/run-daily` endpoint

**API Layer (planned):**
- Purpose: REST endpoints + SSE for the React dashboard
- Location: `backend/app/api/routers/`
- Depends on: All service layers
- Used by: React frontend

**Database Layer (planned):**
- Purpose: SQLAlchemy ORM models + Alembic migrations
- Location: `backend/app/models/`, `backend/app/db/`, `database/`

## Data Flow

### Primary Decision Pipeline (shared by backtester and live executor)

1. Caller invokes `create_provider()` — selects MassiveProvider or SimulatorProvider based on env (`backend/app/services/data_ingestion/market_interface.py:89`)
2. Provider returns `dict[str, pd.DataFrame]` of OHLCV bars via `get_bars()` (`market_interface.py:51`)
3. Feature engineering service computes indicators for (symbol, as_of_date) using only data ≤ as_of_date
4. ML signal model (`services/ml/predict.py`) loads versioned XGBoost artifact and returns signal score
5. LLM reasoning service checks `llm_decisions` cache — if hit, returns cached decision; if miss, calls Cerebras API and persists result
6. Decision (`action, position_size_pct, confidence, rationale, risk_flags`) returned to caller

### Live Paper Trading Flow

1. APScheduler triggers daily job after market close
2. Data ingestion pulls latest bars and news headlines
3. Decision pipeline runs per watchlist symbol (same function as backtester)
4. Risk checks apply (MAX_POSITION_PCT, MAX_POSITIONS, DAILY_LOSS_LIMIT_PCT)
5. Passing decisions submit orders via `alpaca-py` to `https://paper-api.alpaca.markets`
6. Trades, positions, portfolio_snapshots rows written to PostgreSQL

### Market Data Provider Selection

1. Import time: `create_provider()` reads `os.environ.get("MASSIVE_API_KEY")` (`market_interface.py:89`)
2. Key present: returns `MassiveProvider` — live Polygon REST calls with exponential backoff on 429
3. Key absent: returns `SimulatorProvider` wrapping `MarketSimulator`
4. `MarketSimulator` priority: DB replay from `price_bars` if session + rows exist; else GBM synthetic

**State Management:**
- Trade state, positions, portfolio snapshots, decisions all persisted in PostgreSQL
- LLM decisions cached in `llm_decisions` table keyed by `(instrument_id, as_of_date, model_slug, prompt_version)`
- ML model artifacts stored as files in `backend/models/` (git-ignored)

## Key Abstractions

**MarketDataProvider:**
- Purpose: Unified contract hiding whether data comes from live API or simulator
- Examples: `backend/app/services/data_ingestion/market_interface.py`, `massive_provider.py`, `simulator_provider.py`
- Pattern: Abstract Base Class with four abstract methods; factory function `create_provider()` is the sole selection point

**Bar / Quote:**
- Purpose: Immutable, hashable OHLCV and bid/ask data records
- Examples: `backend/app/services/data_ingestion/market_interface.py:21-44`
- Pattern: Frozen dataclasses — safe to cache, put in sets, pass across threads

**Decision Function Contract (to be implemented):**
- Purpose: Shared callable with signature `(symbol, as_of_date, available_data) → Decision`
- Pattern: Pure function — no side effects except DB cache write; called identically from backtester and live executor

## Entry Points

**Market data layer (production entry):**
- Location: `backend/app/services/data_ingestion/market_interface.py:89` — `create_provider()`
- Triggers: Import by any service that needs OHLCV data
- Responsibilities: Provider selection, environment-based routing

**Terminal demo:**
- Location: `market_data_demo.py` (root)
- Triggers: `python market_data_demo.py`
- Responsibilities: Demonstrates all four `MarketDataProvider` methods in the terminal

**Test conftest:**
- Location: `conftest.py` (root)
- Triggers: pytest collection
- Responsibilities: Adds `backend/` to `sys.path` so `from app.*` imports resolve in tests

**FastAPI app entry (planned):**
- Location: `backend/app/main.py` (planned)
- Triggers: `uvicorn app.main:app --reload`
- Responsibilities: Route registration, startup assertions (paper endpoint check), scheduler init

## Architectural Constraints

- **Paper-only rule:** Startup assertion must verify `ALPACA_BASE_URL == https://paper-api.alpaca.markets` and refuse to start otherwise. This is a hard requirement in `services/trading/executor.py`.
- **No lookahead:** Feature computation and LLM context assembly must only access data with `timestamp <= as_of_date`. The news query upper bound must use `as_of_date`, never `datetime.now()`.
- **Shared decision function:** Backtester and live executor must call the same function. Any divergence invalidates the backtest. Do not duplicate this logic.
- **LLM rate limits:** Cerebras free tier is 5 RPM / 1M tokens/day. Decision cache is mandatory for backtesting — always query `llm_decisions` before calling the API.
- **Threading:** Python backend; GBM simulator is deterministic per ticker seed — safe for repeated calls. No module-level mutable state in the market data layer.
- **No real-money path:** No live brokerage execution. Never implement a non-paper order path.

## Anti-Patterns

### Importing concrete providers directly

**What happens:** A service does `from app.services.data_ingestion.massive_provider import MassiveProvider` and instantiates it directly.
**Why it's wrong:** Breaks the offline/CI fallback; tests require `MASSIVE_API_KEY` set in environment.
**Do this instead:** Always call `create_provider()` from `market_interface.py` and use the returned `MarketDataProvider` instance.

### Calling the LLM without checking the cache

**What happens:** A backtesting loop calls the Cerebras API for every (symbol, date) combination.
**Why it's wrong:** At 5 RPM free tier, a multi-year multi-symbol backtest exhausts rate limits and costs unnecessary API calls. Cached decisions already exist for re-runs.
**Do this instead:** Query `llm_decisions` for `(instrument_id, as_of_date, model_slug, prompt_version)` before every LLM call. The unique index enforces no duplicates; use it as the cache key.

### Separate decision logic in backtester vs executor

**What happens:** `backtesting/engine.py` contains its own copy of the feature→signal→decision logic, diverging from `trading/executor.py`.
**Why it's wrong:** Backtest results no longer reflect what the live system does. The capstone's core claim is invalid.
**Do this instead:** Implement one `make_decision(symbol, as_of_date, provider)` function in a shared module (e.g., `services/decision.py`) and import it from both engine and executor.

## Error Handling

**Strategy:** Explicit error propagation with retry logic for external APIs

**Patterns:**
- `MassiveProvider` applies exponential backoff with jitter on HTTP 429 and 5xx responses (`massive_provider.py`)
- LLM client must use `tenacity` `@retry(wait=wait_exponential(min=4, max=60), retry=retry_if_exception_type(RateLimitError))` per plan section 9
- Pydantic validation on all LLM responses — malformed JSON must raise a typed exception, not silently produce a bad decision
- Startup assertion (`assert ALPACA_BASE_URL == ...`) raises at process start — fast fail, not silent misconfiguration

## Cross-Cutting Concerns

**Logging:** Raw LLM prompts and responses logged to `llm_decisions.raw_response` column (required for debugging and demo). General app logging via Python `logging` (stdlib).
**Validation:** Pydantic used for all LLM response parsing and FastAPI request/response schemas.
**Authentication:** Single-operator system; no multi-user auth. API keys read from environment variables (`LLM_API_KEY`, `MASSIVE_API_KEY`, `ALPACA_KEY_ID`, `ALPACA_SECRET_KEY`).

---

*Architecture analysis: 2026-06-25*
