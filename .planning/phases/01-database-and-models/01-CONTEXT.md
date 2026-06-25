# Phase 1: Database and Models - Context

**Gathered:** 2026-06-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Define all 9 SQLAlchemy ORM models, create the `TimestampMixin`, initialize Alembic, generate and apply the first schema migration, add a second seed migration that inserts the initial watchlist symbols into `instruments`, and export `database/schema.sql` via `pg_dump --schema-only`. No service layer code, no API endpoints, no feature engineering — schema foundation only.

</domain>

<decisions>
## Implementation Decisions

### Database Engine
- **D-01:** Use plain PostgreSQL (no TimescaleDB extension). Composite index on `(instrument_id, timestamp)` for `price_bars` is sufficient for the data volume (5-15 symbols × 5yr × 252 days ≈ 20K rows). TimescaleDB adds install overhead without query benefit at this scale.
- **D-02:** SQLAlchemy **sync** `Session` throughout — not `AsyncSession`. The existing data_ingestion layer is fully synchronous; consistency wins. FastAPI endpoints can use a sync DB dependency without issues for a single-operator app.

### ORM Model File Layout
- **D-03:** Domain-grouped files under `backend/app/models/`:
  - `market_data.py` — `Instrument`, `PriceBar`, `NewsArticle`
  - `ml.py` — `MLSignal`, `LLMDecision`
  - `trading.py` — `Trade`, `Position`, `PortfolioSnapshot`
  - `backtest.py` — `BacktestRun`
- **D-04:** `backend/app/models/__init__.py` re-exports all model classes so callers use `from app.models import Instrument, PriceBar, Trade` — no need to know the file layout.
- **D-05:** A shared `TimestampMixin` provides `created_at` and `updated_at` (server-default `now()`, `onupdate=now()`) applied to all tables.
- **D-06:** All primary keys are `Integer` auto-increment (`Identity`), consistent with the existing `instruments.id` FK reference in `market_simulator.py` line 179.

### Instruments Seeding
- **D-07:** Watchlist seeded via a second Alembic migration (`02_seed_instruments.py`) using `op.bulk_insert()` — runs automatically on `alembic upgrade head` so any fresh database gets the watchlist without a separate script.
- **D-08:** Initial watchlist (8 symbols): `AAPL`, `MSFT`, `NVDA`, `GOOGL`, `AMZN`, `META`, `SPY`, `QQQ`. Covers Mag-7 tech + two major index ETFs.
- **D-09:** `instruments` columns: `id` (PK), `symbol` (unique, not null), `name`, `asset_class` (`'equity'` or `'etf'`), `is_active` (bool, default True) + TimestampMixin fields.

### Schema Details (locked by existing code)
- **D-10:** `price_bars` must have: `instrument_id` (FK → instruments.id), `timestamp` (DateTime tz-aware), `open`, `high`, `low`, `close` (Numeric/Float), `volume` (BigInteger), `vwap` (Float, nullable). Composite index on `(instrument_id, timestamp)`. Unique constraint on `(instrument_id, timestamp)`.
- **D-11:** `llm_decisions` unique index on `(instrument_id, as_of_date, model_slug, prompt_version)` — this is the cache key enforced at the DB level.
- **D-12:** `backtest_runs` stores metrics as individual typed columns: `total_return`, `cagr`, `sharpe_ratio`, `max_drawdown`, `win_rate`, `avg_win`, `avg_loss`, `num_trades` (all Float/Integer) — queryable and self-documenting.

### Claude's Discretion
- Watchlist symbol set: AAPL, MSFT, NVDA, GOOGL, AMZN, META, SPY, QQQ (8 symbols)
- `instruments` minimal column set chosen for simplicity
- Backtest metrics as individual columns (not JSONB) for type-safety

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` — DATA-01 and DATA-02 define the 9 tables, TimestampMixin, Alembic requirements, and schema.sql export
- `.planning/ROADMAP.md` — Phase 1 goal and canonical checklist

### Project Context
- `.planning/PROJECT.md` — Key Decisions table (shared decision function, LLM cache key schema)

### Existing Code (schema constraints)
- `backend/app/services/data_ingestion/market_simulator.py` — lines 177-184: raw SQL that defines the required `price_bars` + `instruments` column names and join structure (MUST be compatible)
- `backend/app/services/data_ingestion/market_interface.py` — lines 21-32: `Bar` dataclass defines OHLCV + `vwap` (nullable) field names that must match DB columns

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/app/services/data_ingestion/market_interface.py` — `Bar` dataclass (lines 21-32): defines the canonical field names (`open`, `high`, `low`, `close`, `volume`, `vwap`) that the ORM model columns must mirror
- `conftest.py` — `sys.path` patch for `from app.*` imports: test structure is already set up

### Established Patterns
- `snake_case.py` for all Python files; `PascalCase` for class names (e.g., `MarketDataProvider`, `MassiveProvider`)
- `from __future__ import annotations` at top of every module
- Frozen dataclasses for immutable records — ORM models use regular classes with `__tablename__`
- Factory pattern (`create_provider()`) already established — DB session factory should follow same pattern

### Integration Points
- `market_simulator.py` line 179: `JOIN instruments i ON i.id = pb.instrument_id` — the integer FK relationship between `price_bars` and `instruments` is hardcoded here; schema must be 100% compatible
- `backend/app/db/` — planned location for SQLAlchemy engine, `SessionLocal`, and `get_db()` dependency
- All service layers (features, ml, llm_reasoning, trading, backtesting) will import models via `from app.models import ...`

</code_context>

<specifics>
## Specific Ideas

- The existing `market_simulator.py` SQL query is the ground truth for `price_bars` and `instruments` column names — do not rename them
- `alembic upgrade head` should bring a fresh database to working state (schema + seed data) in one command
- `database/schema.sql` exported via `pg_dump --schema-only` after migration; tracked in git as reference

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 1-Database-and-Models*
*Context gathered: 2026-06-25*
