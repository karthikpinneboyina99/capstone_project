# Technology Stack

**Analysis Date:** 2026-06-25

## Languages

**Primary:**
- Python 3.11+ (runtime 3.14.0 detected locally) — backend, ML pipeline, data ingestion, LLM reasoning
- TypeScript 5.9.3 — React frontend dashboard

**Secondary:**
- JavaScript — build tooling configs (Vite, Tailwind, Vitest)

## Runtime

**Environment:**
- Python: CPython 3.14.0 (local); target 3.11+ per plan
- Node.js: v26.3.0 (local); target Node 20+ per plan

**Package Manager:**
- Python: pip + `requirements.txt` at `backend/requirements.txt`
- Node: npm; lockfile present at `frontend/node_modules/.package-lock.json`
- No yarn.lock or pnpm-lock.yaml detected

## Frameworks

**Core (Backend):**
- FastAPI — async REST API server + WebSocket/SSE endpoints
- Uvicorn (standard extras) — ASGI server

**Core (Frontend):**
- React 18.3.1 — UI framework
- Vite 5.4.21 — build tool and dev server (`@vitejs/plugin-react` 4.7.0)
- React Router DOM 6.30.4 — client-side routing

**Data / ML:**
- SQLAlchemy — ORM
- Alembic — database migrations
- pandas — DataFrame-based data pipeline
- numpy — numerical operations
- scikit-learn — baseline ML preprocessing + model utilities
- xgboost — primary ML signal model (XGBoost regressor on tabular technical features)
- ta — technical indicator library (RSI, MACD, Bollinger Bands, EMA/SMA)

**Scheduling:**
- APScheduler — daily ingestion + signal + decision job scheduling

**Testing (Backend):**
- pytest — test runner
- pytest-asyncio — async test support
- httpx — async HTTP client for FastAPI test client

**Testing (Frontend):**
- Vitest 2.1.9 — test runner (Vite-native)
- @testing-library/react 16.3.2 — component testing
- @playwright/test 1.61.1 — end-to-end browser testing

**Build / Dev:**
- Vite 5.4.21 — frontend bundler
- Autoprefixer 10.5.2 — CSS vendor prefixing
- Docker + docker-compose — containerized local and deploy stack (planned Phase 11)

## Key Dependencies

**Backend Critical:**
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

**Backend ML:**
- `pandas` — core data structure (DataFrames) throughout the pipeline
- `numpy` — array operations
- `scikit-learn` — feature scaling, train/test splits, evaluation
- `xgboost` — XGBoost regressor for signal score
- `ta` — technical indicators (RSI, MACD, Bollinger Bands, SMA, EMA)

**Frontend Critical:**
- `react` 18.3.1 + `react-dom` 18.3.1 — UI layer
- `react-router-dom` 6.30.4 — SPA routing
- `@tanstack/react-query` 5.101.1 — server state management (REST polling)
- `axios` 1.18.1 — HTTP client for API calls
- Native `EventSource` / SSE — real-time server push for portfolio updates and live signals

**Frontend Charts:**
- `lightweight-charts` 4.2.3 — candlestick charts (TradingView library)
- `recharts` 2.15.4 — equity curve, bar charts, general analytics charts

**Frontend Styling:**
- `tailwindcss` 3.4.19 — utility-first CSS framework
- `clsx` 2.1.1 — conditional class name merging

## Configuration

**Environment:**
- Loaded via `python-dotenv` from `.env` (never committed); `.env.example` at repo root tracks placeholder keys
- Key environment variables:
  - `DATABASE_URL` — PostgreSQL connection string
  - `MASSIVE_API_KEY` — Polygon/Massive REST API key (market data); absent → SimulatorProvider fallback
  - `MASSIVE_BASE_URL` — defaults to `https://api.polygon.io`
  - `LLM_API_KEY` — Cerebras API key
  - `LLM_MODEL` — e.g. `gpt-oss-120b`
  - `ALPACA_API_KEY` + `ALPACA_SECRET_KEY` + `ALPACA_BASE_URL` — must be paper endpoint
  - `NEWS_API_KEY` — NewsAPI free tier key

**Build (Frontend):**
- `frontend/` — Vite config (implicit; no separate `vite.config.ts` found in root, generated during scaffold)
- TypeScript strict mode via `tsconfig.json` (in `frontend/`)
- Tailwind config (in `frontend/`)

## Platform Requirements

**Development:**
- Python 3.11+
- Node.js 20+
- PostgreSQL (local or Docker)
- Docker Desktop (optional for local Postgres)

**Production:**
- Backend: Render or Railway (FastAPI + PostgreSQL)
- Frontend: Vercel (static React build)
- CI: GitHub Actions (`.github/workflows/`)

---

*Stack analysis: 2026-06-25*
