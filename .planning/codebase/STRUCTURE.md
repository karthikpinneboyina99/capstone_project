# Codebase Structure

**Last mapped:** 2026-06-25
**Focus:** Directory layout, key locations, naming conventions

---

## Top-Level Layout

```
/
├── backend/                  # Python FastAPI backend
│   ├── app/                  # Application package
│   │   ├── api/              # FastAPI routers (only __pycache__ — source missing)
│   │   │   └── routers/      # Per-domain router modules
│   │   ├── core/             # Config, settings (only __pycache__ — source missing)
│   │   ├── db/               # Database session/engine (only __pycache__ — source missing)
│   │   ├── models/           # SQLAlchemy ORM models (only __pycache__ — source missing)
│   │   ├── schemas/          # Pydantic request/response schemas (only __pycache__ — source missing)
│   │   └── services/         # Domain service layer
│   │       ├── data_ingestion/   # Market data providers ← IMPLEMENTED
│   │       │   ├── market_interface.py    # Abstract base: Bar, Quote, MarketDataProvider
│   │       │   ├── massive_provider.py    # Live data via Polygon.io REST
│   │       │   ├── market_simulator.py    # GBM-based synthetic price generator
│   │       │   └── simulator_provider.py  # MarketDataProvider wrapper for simulator
│   │       ├── backtesting/  # Backtesting engine (only __pycache__ — source missing)
│   │       ├── features/     # ML feature engineering (only __pycache__ — source missing)
│   │       ├── llm_reasoning/ # Cerebras LLM layer (only __pycache__ — source missing)
│   │       ├── ml/           # ML signal models (only __pycache__ — source missing)
│   │       ├── simulation/   # Paper trading simulation (only __pycache__ — source missing)
│   │       └── trading/      # Alpaca paper trade executor (only __pycache__ — source missing)
│   ├── requirements.txt      # Python dependencies (unversioned)
│   └── README.md
│
├── frontend/                 # React dashboard
│   ├── dist/                 # Compiled bundle (only artifact — src/ missing)
│   │   ├── assets/
│   │   │   ├── index-C4lYKhok.js   # Bundled JS
│   │   │   └── index-Cuquz2el.css  # Bundled CSS
│   │   └── index.html
│   └── node_modules/         # Frontend deps (Vite, React, Tailwind, TypeScript, Vitest)
│
├── database/                 # DB-related files
│   └── README.md             # Schema notes (no SQL or migrations present)
│
├── planning/                 # Project planning docs
│   ├── plan.md               # Master build checklist and architecture spec
│   ├── MARKET_DATA_SUMMARY.md  # Completed phase 1 summary
│   ├── MASSIVE_API.md        # Polygon.io API reference
│   └── archive/              # Archived planning docs
│
├── tests/                    # Pytest test suite (market data only)
│   ├── test_market_data_service.py
│   ├── test_massive_provider.py
│   ├── test_polygon_provider.py
│   └── test_providers.py
│
├── conftest.py               # Pytest fixtures (root level)
├── .env.example              # Env var template (never commit .env)
├── .env                      # Local secrets (gitignored)
├── .gitignore
├── CLAUDE.md                 # Project rules and plan reference for Claude
└── .github/
    └── workflows/
        ├── claude.yml                # Claude Code integration
        └── claude-code-review.yml    # PR review automation
```

---

## Key Locations

| What | Where |
|------|-------|
| Market data abstract base | `backend/app/services/data_ingestion/market_interface.py` |
| Live data provider (Polygon) | `backend/app/services/data_ingestion/massive_provider.py` |
| Synthetic data provider (GBM) | `backend/app/services/data_ingestion/market_simulator.py` |
| Simulator wrapper | `backend/app/services/data_ingestion/simulator_provider.py` |
| Python dependencies | `backend/requirements.txt` |
| Env var template | `.env.example` |
| Master build plan | `planning/plan.md` |
| Test fixtures | `conftest.py` |
| Tests | `tests/` |
| Compiled frontend | `frontend/dist/` |
| CI workflows | `.github/workflows/` |

---

## What's Missing (Source Files Not Present)

The following directories exist but contain only `__pycache__` — source `.py` files are absent and must be built:

| Directory | What goes here (per plan) |
|-----------|--------------------------|
| `backend/app/api/routers/` | FastAPI route handlers |
| `backend/app/core/` | `config.py` (Pydantic settings), `security.py` |
| `backend/app/db/` | `session.py` (SQLAlchemy engine/session) |
| `backend/app/models/` | SQLAlchemy ORM models (Bar, Trade, Signal, etc.) |
| `backend/app/schemas/` | Pydantic request/response schemas |
| `backend/app/services/backtesting/` | Backtesting engine |
| `backend/app/services/features/` | Feature engineering pipeline |
| `backend/app/services/llm_reasoning/` | Cerebras LLM decision layer |
| `backend/app/services/ml/` | XGBoost signal model |
| `backend/app/services/simulation/` | Paper trading simulation |
| `backend/app/services/trading/` | Alpaca paper trade executor |
| `frontend/src/` | React source (TypeScript + Tailwind + Vite) |
| `database/` | Alembic migrations, `schema.sql` |
| Root | `main.py` — FastAPI app entry point |

---

## Naming Conventions

- **Python packages:** `snake_case` directories with `__init__.py`
- **Python modules:** `snake_case.py`
- **Python classes:** `PascalCase`
- **Provider pattern:** Abstract base in `market_interface.py`, concrete implementations as `*_provider.py`
- **Tests:** `test_*.py` in `tests/` directory, mirroring service names
- **Env vars:** `SCREAMING_SNAKE_CASE`, prefixed by service (`ALPACA_*`, `LLM_*`, `MASSIVE_*`)
- **Frontend (planned):** TypeScript + React, Vite bundler, Tailwind CSS

---

## Where to Add New Code

| New capability | Location |
|---------------|----------|
| New FastAPI endpoint | `backend/app/api/routers/<domain>.py` |
| New SQLAlchemy model | `backend/app/models/<entity>.py` |
| New Pydantic schema | `backend/app/schemas/<entity>.py` |
| New market data provider | `backend/app/services/data_ingestion/<name>_provider.py` |
| ML features | `backend/app/services/features/` |
| LLM prompts/logic | `backend/app/services/llm_reasoning/` |
| Database migration | `database/migrations/` (Alembic, once initialized) |
| React component (planned) | `frontend/src/components/` |
| New tests | `tests/test_<module>.py` |
