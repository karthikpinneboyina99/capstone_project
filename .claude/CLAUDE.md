<!-- GSD:project-start source:PROJECT.md -->

## Project

**AI Trading Workstation**

An AI-assisted research and paper-trading platform for US stocks/ETFs. It pulls historical and live market data for a watchlist, engineers technical features and generates an XGBoost ML signal per symbol per day, feeds that signal plus recent price action and news headlines to an LLM (Cerebras `gpt-oss-120b`), which outputs a structured trade decision with a plain-English rationale, then backtests that combined ML+LLM strategy and runs it live against Alpaca's paper trading API — everything surfaced in a React dashboard. This is a capstone/portfolio project for a single operator; no real money is ever touched.

**Core Value:** The LLM override story: when the AI's rationale explains why it ignored a strong quant signal because of negative news or risk flags, that is the demo — everything else serves this moment.

### Constraints

- **Paper trading only:** `ALPACA_BASE_URL` must equal `https://paper-api.alpaca.markets`; startup assertion in `trading/executor.py` must refuse to start otherwise.
- **No lookahead:** All feature computation and LLM news queries must use data with `timestamp <= as_of_date`; never use `datetime.now()` as the upper bound in backtest context.
- **LLM API:** Cerebras only — `openai` SDK with `base_url=https://api.cerebras.ai/v1`, `api_key=LLM_API_KEY`, model `gpt-oss-120b`.
- **No secrets in git:** Only `.env.example` (with placeholders) is committed; `.env` is git-ignored.
- **Forward-return label:** Fixed at 5 trading days; do not change after first training run.

<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->

## Technology Stack

## Languages

- Python 3.11+ (runtime 3.14.0 detected locally) — backend, ML pipeline, data ingestion, LLM reasoning
- TypeScript 5.9.3 — React frontend dashboard
- JavaScript — build tooling configs (Vite, Tailwind, Vitest)

## Runtime

- Python: CPython 3.14.0 (local); target 3.11+ per plan
- Node.js: v26.3.0 (local); target Node 20+ per plan
- Python: pip + `requirements.txt` at `backend/requirements.txt`
- Node: npm; lockfile present at `frontend/node_modules/.package-lock.json`
- No yarn.lock or pnpm-lock.yaml detected

## Frameworks

- FastAPI — async REST API server + WebSocket/SSE endpoints
- Uvicorn (standard extras) — ASGI server
- React 18.3.1 — UI framework
- Vite 5.4.21 — build tool and dev server (`@vitejs/plugin-react` 4.7.0)
- React Router DOM 6.30.4 — client-side routing
- SQLAlchemy — ORM
- Alembic — database migrations
- pandas — DataFrame-based data pipeline
- numpy — numerical operations
- scikit-learn — baseline ML preprocessing + model utilities
- xgboost — primary ML signal model (XGBoost regressor on tabular technical features)
- ta — technical indicator library (RSI, MACD, Bollinger Bands, EMA/SMA)
- APScheduler — daily ingestion + signal + decision job scheduling
- pytest — test runner
- pytest-asyncio — async test support
- httpx — async HTTP client for FastAPI test client
- Vitest 2.1.9 — test runner (Vite-native)
- @testing-library/react 16.3.2 — component testing
- @playwright/test 1.61.1 — end-to-end browser testing
- Vite 5.4.21 — frontend bundler
- Autoprefixer 10.5.2 — CSS vendor prefixing
- Docker + docker-compose — containerized local and deploy stack (planned Phase 11)

## Key Dependencies

- `fastapi` — web framework; REST API + SSE streaming
- `sqlalchemy` — ORM; all DB interaction goes through models
- `alembic` — migration management for PostgreSQL schema
- `psycopg2-binary` — PostgreSQL driver
- `pydantic` + `pydantic-settings` — input validation, config management, schemas
- `python-dotenv` — `.env` loading
- `openai` — OpenAI-compatible SDK, pointed at Cerebras endpoint (`https://api.cerebras.ai/v1`)
- `alpaca-py` — Alpaca market data + paper trading order execution SDK
- `yfinance` — free historical OHLCV data (no API key required); fallback / supplemental data source
- `requests` — HTTP for MassiveProvider (Polygon REST API)
- `apscheduler` — recurring job scheduling
- `pandas` — core data structure (DataFrames) throughout the pipeline
- `numpy` — array operations
- `scikit-learn` — feature scaling, train/test splits, evaluation
- `xgboost` — XGBoost regressor for signal score
- `ta` — technical indicators (RSI, MACD, Bollinger Bands, SMA, EMA)
- `react` 18.3.1 + `react-dom` 18.3.1 — UI layer
- `react-router-dom` 6.30.4 — SPA routing
- `@tanstack/react-query` 5.101.1 — server state management (REST polling)
- `axios` 1.18.1 — HTTP client for API calls
- Native `EventSource` / SSE — real-time server push for portfolio updates and live signals
- `lightweight-charts` 4.2.3 — candlestick charts (TradingView library)
- `recharts` 2.15.4 — equity curve, bar charts, general analytics charts
- `tailwindcss` 3.4.19 — utility-first CSS framework
- `clsx` 2.1.1 — conditional class name merging

## Configuration

- Loaded via `python-dotenv` from `.env` (never committed); `.env.example` at repo root tracks placeholder keys
- Key environment variables:
- `frontend/` — Vite config (implicit; no separate `vite.config.ts` found in root, generated during scaffold)
- TypeScript strict mode via `tsconfig.json` (in `frontend/`)
- Tailwind config (in `frontend/`)

## Platform Requirements

- Python 3.11+
- Node.js 20+
- PostgreSQL (local or Docker)
- Docker Desktop (optional for local Postgres)
- Backend: Render or Railway (FastAPI + PostgreSQL)
- Frontend: Vercel (static React build)
- CI: GitHub Actions (`.github/workflows/`)

<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->

## Conventions

## Naming Patterns

- Python source files: `snake_case.py` (e.g., `market_interface.py`, `simulator_provider.py`, `massive_provider.py`)
- Test files: `test_<module_name>.py` prefix (e.g., `test_market_interface.py`, `test_massive_provider.py`)
- Private/internal helpers: underscore-prefixed names at module level (e.g., `_KNOWN`, `_DEFAULTS`, `_DEFAULT_BASE`, `_RETRY_ON`, `_TickerParams`, `_params_for`)
- PascalCase for all classes: `MarketDataProvider`, `MassiveProvider`, `SimulatorProvider`, `MarketSimulator`
- Private/internal dataclasses: underscore prefix PascalCase: `_TickerParams`
- Test classes: `TestFoo` / `TestFooBar` grouping by feature or scenario (e.g., `TestBar`, `TestGetBars`, `TestRetryLogic`)
- `snake_case` for all functions and methods: `get_bars`, `get_latest_quote`, `create_provider`, `_fetch_aggs`, `_to_df`
- Private helpers: leading underscore: `_get`, `_fetch_aggs`, `_to_df`, `_get_snapshots`
- Factory functions: verb-noun: `create_provider()`
- Module-level constants: `UPPER_SNAKE_CASE` (e.g., `_DEFAULT_BASE`, `_KNOWN`, `_RETRY_ON`, `_DEFAULTS`, `EXPECTED_COLS`, `SIM`, `PROVIDER`)
- Local variables: `snake_case`
- Type-hinted intermediate dicts: lowercase with type annotation (e.g., `results: dict[str, pd.DataFrame] = {}`)
- All public method signatures carry full type hints
- `from __future__ import annotations` used in every module for PEP 604 union syntax (`str | None`, `float | None`)
- Return types always annotated: `-> dict[str, pd.DataFrame]`, `-> dict[str, Quote]`, `-> None`
- Dataclass fields typed directly in the class body

## Code Style

- No dedicated formatter config detected (no `.prettierrc`, `pyproject.toml`, or `ruff.toml`)
- Consistent 4-space indentation throughout
- 79–100 character line width (PEP 8 style)
- Trailing commas in multi-line function calls and dict literals
- No explicit linter config detected
- `# type: ignore[misc]` used sparingly in test files only (for frozen dataclass mutation tests)
- `# noqa` not used in production code
- `from __future__ import annotations` is the first import in all service modules
- Standard library imports first, then third-party (pandas, numpy, requests), then local (`.market_interface`, `.market_simulator`)
- Relative imports used within the `data_ingestion` package (e.g., `from .market_interface import Bar`)
- Absolute imports in test files (e.g., `from app.services.data_ingestion.market_interface import Bar`)

## Import Organization

- None — `sys.path` is patched in `conftest.py` to add `backend/` so tests use `app.*` imports

## Module-Level Structure Pattern

## Docstrings

- What the module does
- How provider selection works (for interface/factory modules)
- Which env vars drive behavior
- Key design guarantees

## Error Handling

- API 429/5xx: exponential backoff loop in `MassiveProvider._get()`, raises `RuntimeError("Massive API rate limit: max retries exceeded")` after 5 attempts
- API body error: `raise RuntimeError(f"Massive API error: {body.get('error', 'unknown')}")`
- Missing required env var: let `os.environ[key]` raise `KeyError` naturally — no custom wrapping
- Empty/inverted date ranges: return empty DataFrame with correct columns (no exception)
- Unknown ticker fallback: return synthetic GBM data (no exception)
- Custom exception classes (not defined anywhere in the current codebase)
- Logging via the `logging` module — no logger calls found in production code

## Abstract Base Classes

## Dataclasses

- Frozen makes them hashable and immutable
- Field comments used for non-obvious semantics (e.g., `# trading date (ET)`)

## Configuration / Environment

- Required vars: let `KeyError` propagate
- Optional vars: provide sensible defaults inline
- Never read env vars at module import time (deferred to constructor)

## Section Separators

## Paper-Trading Safety

<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->

## Architecture

## System Overview

```text

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

- All market data consumers call `create_provider()` — never import a concrete provider directly
- The backtester and live executor MUST call the exact same `features → ML signal → LLM decision` function — divergence invalidates the backtest
- LLM decisions are cached in the `llm_decisions` DB table (unique key: `instrument_id + as_of_date + model_slug + prompt_version`) — never re-call the API for a cached row
- Paper trading only: startup assertion checks `ALPACA_BASE_URL == https://paper-api.alpaca.markets`
- Simulation fallback: when `MASSIVE_API_KEY` is absent, data flows through GBM synthetic generator — CI/tests never need external API access

## Layers

- Purpose: Supply OHLCV bars and quotes to all upstream consumers
- Location: `backend/app/services/data_ingestion/`
- Contains: ABC (`market_interface.py`), two concrete providers, one simulator
- Depends on: PostgreSQL `price_bars` table (optional, for DB replay), Massive/Polygon API (optional)
- Used by: Feature engineering, backtesting engine, live trading executor
- Purpose: Compute SMA/EMA/RSI/MACD/Bollinger Bands/volatility/volume z-scores per symbol per day
- Location: `backend/app/services/features/`
- Contains: Feature computation functions (no lookahead — only bars ≤ as_of_date)
- Depends on: data_ingestion layer
- Used by: ml/ train and predict, backtesting engine, live executor
- Purpose: XGBoost regressor predicts 5-day forward return; normalized to signal score [-1, 1]
- Location: `backend/app/services/ml/`
- Contains: `train.py` (walk-forward validation), `predict.py` (load artifact, score single day)
- Depends on: features/, price_bars DB table
- Used by: backtesting engine, live executor
- Purpose: Convert (ML signal, price summary, news, position state) → structured trade decision
- Location: `backend/app/services/llm_reasoning/`
- Contains: Prompt builder, Cerebras API client wrapper, Pydantic response validator, DB cache check
- Depends on: ml/, news_articles DB table, llm_decisions DB table
- Used by: backtesting engine, live executor
- Purpose: Day-by-day event-driven historical replay; fills simulated at D+1 open
- Location: `backend/app/services/backtesting/`
- Contains: `engine.py`, metrics module (CAGR, Sharpe, max drawdown, win rate)
- Depends on: data_ingestion, features, ml, llm_reasoning layers
- Used by: API router (triggered via POST), CLI
- Purpose: Run daily decision pipeline and place paper orders via Alpaca
- Location: `backend/app/services/trading/`
- Contains: `executor.py`, risk check module
- Depends on: data_ingestion, features, ml, llm_reasoning layers, `alpaca-py`
- Used by: APScheduler job or `/jobs/run-daily` endpoint
- Purpose: REST endpoints + SSE for the React dashboard
- Location: `backend/app/api/routers/`
- Depends on: All service layers
- Used by: React frontend
- Purpose: SQLAlchemy ORM models + Alembic migrations
- Location: `backend/app/models/`, `backend/app/db/`, `database/`

## Data Flow

### Primary Decision Pipeline (shared by backtester and live executor)

### Live Paper Trading Flow

### Market Data Provider Selection

- Trade state, positions, portfolio snapshots, decisions all persisted in PostgreSQL
- LLM decisions cached in `llm_decisions` table keyed by `(instrument_id, as_of_date, model_slug, prompt_version)`
- ML model artifacts stored as files in `backend/models/` (git-ignored)

## Key Abstractions

- Purpose: Unified contract hiding whether data comes from live API or simulator
- Examples: `backend/app/services/data_ingestion/market_interface.py`, `massive_provider.py`, `simulator_provider.py`
- Pattern: Abstract Base Class with four abstract methods; factory function `create_provider()` is the sole selection point
- Purpose: Immutable, hashable OHLCV and bid/ask data records
- Examples: `backend/app/services/data_ingestion/market_interface.py:21-44`
- Pattern: Frozen dataclasses — safe to cache, put in sets, pass across threads
- Purpose: Shared callable with signature `(symbol, as_of_date, available_data) → Decision`
- Pattern: Pure function — no side effects except DB cache write; called identically from backtester and live executor

## Entry Points

- Location: `backend/app/services/data_ingestion/market_interface.py:89` — `create_provider()`
- Triggers: Import by any service that needs OHLCV data
- Responsibilities: Provider selection, environment-based routing
- Location: `market_data_demo.py` (root)
- Triggers: `python market_data_demo.py`
- Responsibilities: Demonstrates all four `MarketDataProvider` methods in the terminal
- Location: `conftest.py` (root)
- Triggers: pytest collection
- Responsibilities: Adds `backend/` to `sys.path` so `from app.*` imports resolve in tests
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

### Calling the LLM without checking the cache

### Separate decision logic in backtester vs executor

## Error Handling

- `MassiveProvider` applies exponential backoff with jitter on HTTP 429 and 5xx responses (`massive_provider.py`)
- LLM client must use `tenacity` `@retry(wait=wait_exponential(min=4, max=60), retry=retry_if_exception_type(RateLimitError))` per plan section 9
- Pydantic validation on all LLM responses — malformed JSON must raise a typed exception, not silently produce a bad decision
- Startup assertion (`assert ALPACA_BASE_URL == ...`) raises at process start — fast fail, not silent misconfiguration

## Cross-Cutting Concerns

<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->

## Project Skills

| Skill | Description | Path |
|-------|-------------|------|
| cerebras | Reference for Cerebras Cloud's free, ultra-fast LLM inference API (OpenAI-compatible, ~3000 tokens/sec, no credit card required). Use this skill whenever Cerebras, Cerebras Cloud, cerebras.ai, api.cerebras.ai, or its free models (gpt-oss-120b, zai-glm-4.7) come up -- for evaluating or adding an LLM provider, comparing free inference options against OpenRouter, debugging Cerebras rate limits or 429 errors, or writing any code that calls the Cerebras API. Always check this skill before writing Cerebras integration code: the model lineup and free-tier rate limits change over time, and this file lists the live docs to re-verify against. | `.claude/skills/cerebras/SKILL.md` |
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->

## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:

- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->

## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
