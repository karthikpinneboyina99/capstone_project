# Phase 1: Database and Models - Research

**Researched:** 2026-06-25
**Domain:** PostgreSQL schema design, SQLAlchemy 2.x ORM, Alembic migrations
**Confidence:** MEDIUM

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Plain PostgreSQL (no TimescaleDB). Composite index on `(instrument_id, timestamp)` for `price_bars`.
- **D-02:** SQLAlchemy sync `Session` throughout — not `AsyncSession`.
- **D-03:** Domain-grouped files: `market_data.py`, `ml.py`, `trading.py`, `backtest.py` under `backend/app/models/`.
- **D-04:** `backend/app/models/__init__.py` re-exports all model classes.
- **D-05:** `TimestampMixin` provides `created_at` and `updated_at` for all tables.
- **D-06:** All primary keys are `Integer` auto-increment (`Identity`).
- **D-07:** Watchlist seeded via second Alembic migration (`02_seed_instruments.py`) using `op.bulk_insert()`.
- **D-08:** Initial watchlist: `AAPL`, `MSFT`, `NVDA`, `GOOGL`, `AMZN`, `META`, `SPY`, `QQQ`.
- **D-09:** `instruments` columns: `id`, `symbol`, `name`, `asset_class`, `is_active` + TimestampMixin fields.
- **D-10:** `price_bars` columns: `instrument_id` (FK), `timestamp` (DateTime tz-aware), `open`, `high`, `low`, `close` (Numeric/Float), `volume` (BigInteger), `vwap` (Float, nullable). Composite index + unique constraint on `(instrument_id, timestamp)`.
- **D-11:** `llm_decisions` unique index on `(instrument_id, as_of_date, model_slug, prompt_version)`.
- **D-12:** `backtest_runs` stores metrics as individual typed columns (not JSONB).

### Claude's Discretion
- Watchlist symbol set: AAPL, MSFT, NVDA, GOOGL, AMZN, META, SPY, QQQ (8 symbols)
- `instruments` minimal column set chosen for simplicity
- Backtest metrics as individual columns for type-safety

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DATA-01 | All 9 SQLAlchemy ORM models (instruments, price_bars, news_articles, ml_signals, llm_decisions, trades, positions, portfolio_snapshots, backtest_runs) with correct foreign keys, indexes, and TimestampMixin | SQLAlchemy 2.x DeclarativeBase + mapped_column patterns; schema locked by market_simulator.py raw SQL |
| DATA-02 | Alembic initialized; first migration generated and applied; `database/schema.sql` auto-generated via `pg_dump --schema-only` | Alembic init workflow; two-migration strategy (schema + seed); pg_dump command pattern |
</phase_requirements>

## Summary

This phase creates the complete PostgreSQL schema as the foundation all later phases depend on. The critical constraint is that `price_bars` and `instruments` column names are already hardcoded in `backend/app/services/data_ingestion/market_simulator.py` lines 177-184 — the ORM model must match that raw SQL exactly or the existing market data layer breaks immediately.

SQLAlchemy 2.0.51 (installed) uses the new `DeclarativeBase` + `Mapped[T]` + `mapped_column()` pattern. The old `declarative_base()` function still works but is considered legacy. All 9 models should use the new style for consistency and better IDE/mypy support. The sync `Session` pattern (decided D-02) is straightforward with FastAPI's `Depends(get_db)` generator — appropriate for single-operator use.

Alembic 1.18.4 (installed) workflow is: `alembic init alembic` → edit `env.py` to import `Base` → `alembic revision --autogenerate -m "initial schema"` → manually create second migration with `op.bulk_insert()` → `alembic upgrade head`. The `database/schema.sql` export via `pg_dump --schema-only` is a one-liner after migration runs; it is committed to git as a human-readable schema reference (not used by application code).

**Primary recommendation:** Build models file-by-file in dependency order (instruments first, then price_bars, then others that FK to instruments), verify the `price_bars` raw SQL query in market_simulator.py still passes after each model addition, then run Alembic autogenerate and manually add the seed migration.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| ORM model definitions | Database / Storage | — | Pure schema layer; no business logic |
| SQLAlchemy engine + session | Database / Storage | API / Backend | Engine lives in `db/`; sessions injected into route handlers |
| Alembic migration execution | Database / Storage | — | DDL schema management |
| Seed data insertion | Database / Storage | — | Migration 02 via op.bulk_insert |
| schema.sql export | Database / Storage | — | pg_dump artifact; committed to git |
| FastAPI DB dependency | API / Backend | Database / Storage | `get_db()` in `db/session.py`; imported by routers |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| sqlalchemy | 2.0.51 [VERIFIED: pip show] | ORM, connection pooling, session management | Project stack fixed; 2.x new-style API used |
| alembic | 1.18.4 [VERIFIED: pip show] | Schema migrations; autogenerate + seed | Paired with SQLAlchemy; project stack fixed |
| psycopg2-binary | 2.9.12 [VERIFIED: pip show] | PostgreSQL driver (sync) | Binary wheel; 3.14 wheels shipped April 2026 |
| fastapi | (in requirements.txt) [ASSUMED] | ASGI framework providing `Depends` DI | Project stack fixed |
| pydantic-settings | (in requirements.txt) [ASSUMED] | `DATABASE_URL` config from `.env` | Standard for FastAPI config management |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| python-dotenv | (in requirements.txt) [ASSUMED] | Load `.env` into os.environ | Dev/test environment; pydantic-settings consumes it |

**Installation (all already in requirements.txt — no new packages needed for this phase):**
```bash
pip install -r backend/requirements.txt
```

## Package Legitimacy Audit

All packages in this phase are already installed, pre-existing in `backend/requirements.txt`, and well-established in the Python ecosystem. PyPI legitimacy checker reports `SUS` for all of them due to missing download count data from the PyPI registry API (a known limitation of the checker for PyPI packages), but each has a verified source repository and many years of history.

| Package | Registry | Age | Source Repo | Verdict | Disposition |
|---------|----------|-----|-------------|---------|-------------|
| sqlalchemy | PyPI | 20+ yrs | github.com/sqlalchemy/sqlalchemy | SUS (download data unavailable) | Approved — pre-installed, canonical ORM |
| alembic | PyPI | 12+ yrs | github.com/sqlalchemy/alembic | SUS (download data unavailable) | Approved — pre-installed, standard migration tool |
| psycopg2-binary | PyPI | 15+ yrs | psycopg.org | SUS (download data unavailable) | Approved — pre-installed, 3.14 wheel confirmed |
| fastapi | PyPI | 6+ yrs | github.com/fastapi/fastapi | SUS (download data unavailable) | Approved — pre-installed, project stack fixed |
| pydantic-settings | PyPI | 3+ yrs | github.com/pydantic/pydantic-settings | SUS (download data unavailable) | Approved — pre-installed |

**Packages removed due to SLOP verdict:** none
**Packages flagged as suspicious SUS:** All flagged only due to PyPI download-count API limitation — not genuine concerns. All are pre-installed, have well-known source repos, and are locked in requirements.txt.

**No new packages are introduced by this phase.**

## Architecture Patterns

### System Architecture Diagram

```
  .env / pydantic-settings
         │
         ▼
  backend/app/core/config.py      ← DATABASE_URL (postgres://...)
         │
         ▼
  backend/app/db/base.py          ← DeclarativeBase (class Base)
         │
         ├──── backend/app/models/market_data.py   (Instrument, PriceBar, NewsArticle)
         ├──── backend/app/models/ml.py            (MLSignal, LLMDecision)
         ├──── backend/app/models/trading.py       (Trade, Position, PortfolioSnapshot)
         └──── backend/app/models/backtest.py      (BacktestRun)
                      │
                      ▼
  backend/app/models/__init__.py  ← re-exports all 9 model classes
         │
         ▼
  backend/app/db/session.py       ← engine, SessionLocal, get_db()
         │
         ▼
  alembic/env.py                  ← imports Base.metadata, reads DATABASE_URL
         │
    ┌────┴────┐
    ▼         ▼
  Migration 01       Migration 02
  (autogenerate      (manual:
   all 9 tables)      op.bulk_insert
                      8 instruments)
         │
         ▼
  PostgreSQL (local / Docker)
         │
         ▼
  pg_dump --schema-only → database/schema.sql  (committed to git)
```

### Recommended Project Structure

```
backend/app/
├── core/
│   └── config.py          # Settings(BaseSettings): DATABASE_URL, etc.
├── db/
│   ├── base.py            # class Base(DeclarativeBase): pass
│   └── session.py         # engine, SessionLocal, get_db()
├── models/
│   ├── __init__.py        # from .market_data import ...; from .ml import ...; etc.
│   ├── market_data.py     # Instrument, PriceBar, NewsArticle
│   ├── ml.py              # MLSignal, LLMDecision
│   ├── trading.py         # Trade, Position, PortfolioSnapshot
│   └── backtest.py        # BacktestRun
alembic/
├── env.py                 # configured to import Base + read DATABASE_URL
├── script.py.mako
└── versions/
    ├── 001_initial_schema.py      # autogenerated
    └── 002_seed_instruments.py    # manual bulk_insert
database/
└── schema.sql             # pg_dump --schema-only output (committed)
```

### Pattern 1: SQLAlchemy 2.x DeclarativeBase + TimestampMixin

**What:** Define a shared `Base` class and a `TimestampMixin` that any model class can inherit from.
**When to use:** All 9 model classes. The mixin fields get copied at class creation time.

```python
# Source: https://docs.sqlalchemy.org/en/20/orm/declarative_mixins.html
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
```

### Pattern 2: Mapped Column with ForeignKey, Index, UniqueConstraint

**What:** Declare columns inline using `Mapped[T]` and `mapped_column()`. Constraints go in `__table_args__`.

```python
# Source: https://docs.sqlalchemy.org/en/20/orm/declarative_tables.html
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Float, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship


class PriceBar(TimestampMixin, Base):
    __tablename__ = "price_bars"
    __table_args__ = (
        UniqueConstraint("instrument_id", "timestamp", name="uq_price_bars_instrument_ts"),
        Index("ix_price_bars_instrument_ts", "instrument_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(nullable=False)  # tz-aware UTC
    timeframe: Mapped[str] = mapped_column(nullable=False, default="1d")
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    vwap: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    instrument: Mapped["Instrument"] = relationship(back_populates="price_bars")
```

### Pattern 3: Alembic env.py Configuration

**What:** Wire Alembic's autogenerate to detect all models.
**When to use:** Must import all model modules before setting `target_metadata`.

```python
# Source: https://alembic.sqlalchemy.org/en/latest/autogenerate.html
# alembic/env.py  (key additions to the generated template)
import os
from app.db.base import Base
import app.models  # noqa: F401  ← triggers all model imports via __init__.py

target_metadata = Base.metadata

# In run_migrations_online():
config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
```

### Pattern 4: Alembic op.bulk_insert Seed Migration

**What:** Insert static data as part of a migration so `alembic upgrade head` is idempotent.
**When to use:** Migration 002 for the 8 watchlist instruments.

```python
# Source: https://alembic.sqlalchemy.org/en/latest/ops.html
from alembic import op
from sqlalchemy import table, column, String, Boolean, Integer

def upgrade() -> None:
    instruments_table = table(
        "instruments",
        column("symbol", String),
        column("name", String),
        column("asset_class", String),
        column("is_active", Boolean),
    )
    op.bulk_insert(
        instruments_table,
        [
            {"symbol": "AAPL",  "name": "Apple Inc.",            "asset_class": "equity", "is_active": True},
            {"symbol": "MSFT",  "name": "Microsoft Corporation", "asset_class": "equity", "is_active": True},
            {"symbol": "NVDA",  "name": "NVIDIA Corporation",    "asset_class": "equity", "is_active": True},
            {"symbol": "GOOGL", "name": "Alphabet Inc.",         "asset_class": "equity", "is_active": True},
            {"symbol": "AMZN",  "name": "Amazon.com Inc.",       "asset_class": "equity", "is_active": True},
            {"symbol": "META",  "name": "Meta Platforms Inc.",   "asset_class": "equity", "is_active": True},
            {"symbol": "SPY",   "name": "SPDR S&P 500 ETF",     "asset_class": "etf",    "is_active": True},
            {"symbol": "QQQ",   "name": "Invesco QQQ Trust",     "asset_class": "etf",    "is_active": True},
        ],
    )

def downgrade() -> None:
    op.execute(
        "DELETE FROM instruments WHERE symbol IN "
        "('AAPL','MSFT','NVDA','GOOGL','AMZN','META','SPY','QQQ')"
    )
```

### Pattern 5: FastAPI sync get_db dependency

**What:** Provide a `Session` per request via FastAPI `Depends`.
**When to use:** All route handlers that need DB access (Phase 3 onward).

```python
# Source: FastAPI + SQLAlchemy official SQL tutorial (sync pattern)
# backend/app/db/session.py
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

### Anti-Patterns to Avoid

- **Importing `Base` from models/**: `Base` must live in `db/base.py` and be imported by models — not the reverse. If models define `Base`, circular import breaks `alembic/env.py`.
- **Not importing all models in env.py**: Alembic autogenerate only detects tables whose models have been imported. Missing an import → that table is silently dropped from the migration. The `import app.models` line in env.py must force-load all 4 model files.
- **Omitting `timeframe` column from price_bars**: `market_simulator.py` line 181 queries `pb.timeframe = :tf`. The ORM model must include this column or the DB replay mode fails.
- **Using `declarative_base()` (legacy API)**: Works but triggers deprecation warnings in SQLAlchemy 2.x. All new code should use `class Base(DeclarativeBase): pass`.
- **Setting `server_default` vs `default` for timestamps**: Use `server_default=func.now()` for DB-side default (migration-safe, works even from raw SQL inserts). Using Python-side `default=datetime.utcnow` breaks if rows are inserted outside the ORM.
- **Timezone-naive `DateTime` for `price_bars.timestamp`**: Must store UTC timezone-aware datetimes. Use `DateTime(timezone=True)` in the mapped_column to match how market_simulator.py passes `pd.Timestamp(from_date, tz="UTC")`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Schema migrations | Manual `ALTER TABLE` scripts | Alembic autogenerate | Handles column type changes, index tracking, downgrade paths automatically |
| Seed data management | Separate Python script | `op.bulk_insert()` in migration | Migration atomicity — seed runs inside the same transaction as schema creation |
| Connection pool | Custom connection management | SQLAlchemy engine default pool | Built-in QueuePool handles reconnects, `pool_pre_ping` detects stale connections |
| Timestamp tracking | Manual `datetime.utcnow()` assignments | `server_default=func.now()` | DB-side default is set even for rows inserted via raw SQL or other tools |
| Unique constraint enforcement | Application-level duplicate checking | DB-level `UniqueConstraint` | DB enforces it atomically; application checks have TOCTOU races |

**Key insight:** The Alembic autogenerate + `op.bulk_insert` pattern means `alembic upgrade head` is the only command needed to bring any fresh database to production-ready state — schema + seed data atomically.

## Exact 9-Table Schema (locked by existing code)

### Table: `instruments`
| Column | Type | Constraints |
|--------|------|-------------|
| id | Integer | PK, auto-increment |
| symbol | String(20) | NOT NULL, UNIQUE |
| name | String(200) | nullable |
| asset_class | String(20) | nullable ('equity' or 'etf') |
| is_active | Boolean | NOT NULL, server_default=True |
| created_at | DateTime(tz=True) | NOT NULL, server_default=now() |
| updated_at | DateTime(tz=True) | NOT NULL, server_default=now(), onupdate |

**Cross-reference:** `market_simulator.py:179` — `JOIN instruments i ON i.id = pb.instrument_id` — confirms integer PK and `symbol` column.

### Table: `price_bars`
| Column | Type | Constraints |
|--------|------|-------------|
| id | Integer | PK, auto-increment |
| instrument_id | Integer | FK → instruments.id, NOT NULL |
| timestamp | DateTime(tz=True) | NOT NULL |
| timeframe | String(10) | NOT NULL, default '1d' |
| open | Float | NOT NULL |
| high | Float | NOT NULL |
| low | Float | NOT NULL |
| close | Float | NOT NULL |
| volume | BigInteger | NOT NULL |
| vwap | Float | nullable |
| created_at | DateTime(tz=True) | NOT NULL |
| updated_at | DateTime(tz=True) | NOT NULL |

**Indexes:**
- `UniqueConstraint("instrument_id", "timestamp")` — prevents duplicate bars
- `Index("ix_price_bars_instrument_ts", "instrument_id", "timestamp")` — composite query index

**Critical:** `timeframe` column is required. `market_simulator.py:181` queries `pb.timeframe = :tf` (value `'1d'`). [VERIFIED: read from file]

**Cross-reference:** `market_interface.py:21-32` Bar dataclass fields: `ticker`, `date`, `open`, `high`, `low`, `close`, `volume`, `vwap` — all match column names. [VERIFIED: read from file]

### Table: `news_articles`
| Column | Type | Constraints |
|--------|------|-------------|
| id | Integer | PK |
| instrument_id | Integer | FK → instruments.id, NOT NULL |
| headline | Text | NOT NULL |
| source | String(100) | nullable |
| url | Text | nullable |
| published_at | DateTime(tz=True) | NOT NULL |
| sentiment_score | Float | nullable |
| created_at | DateTime(tz=True) | NOT NULL |
| updated_at | DateTime(tz=True) | NOT NULL |

**Index:** `Index("ix_news_articles_instrument_published", "instrument_id", "published_at")` — supports `published_at <= as_of_date` queries for no-lookahead filtering.

### Table: `ml_signals`
| Column | Type | Constraints |
|--------|------|-------------|
| id | Integer | PK |
| instrument_id | Integer | FK → instruments.id, NOT NULL |
| as_of_date | Date | NOT NULL |
| signal_score | Float | NOT NULL |
| model_version | String(50) | NOT NULL |
| features_json | Text | nullable (JSON blob of top features) |
| created_at | DateTime(tz=True) | NOT NULL |
| updated_at | DateTime(tz=True) | NOT NULL |

**Unique constraint:** `(instrument_id, as_of_date, model_version)` — one signal per symbol per day per model version.

### Table: `llm_decisions`
| Column | Type | Constraints |
|--------|------|-------------|
| id | Integer | PK |
| instrument_id | Integer | FK → instruments.id, NOT NULL |
| as_of_date | Date | NOT NULL |
| model_slug | String(100) | NOT NULL (e.g., 'gpt-oss-120b') |
| prompt_version | String(50) | NOT NULL |
| action | String(10) | NOT NULL ('buy'/'sell'/'hold') |
| position_size_pct | Float | NOT NULL |
| confidence | Float | NOT NULL |
| rationale | Text | NOT NULL |
| risk_flags | Text | nullable (JSON array) |
| raw_prompt | Text | NOT NULL |
| raw_response | Text | NOT NULL |
| created_at | DateTime(tz=True) | NOT NULL |
| updated_at | DateTime(tz=True) | NOT NULL |

**Unique index:** `(instrument_id, as_of_date, model_slug, prompt_version)` — this is the mandatory cache key (D-11). [VERIFIED: locked decision D-11]

### Table: `trades`
| Column | Type | Constraints |
|--------|------|-------------|
| id | Integer | PK |
| instrument_id | Integer | FK → instruments.id, NOT NULL |
| alpaca_order_id | String(100) | nullable, unique (idempotency) |
| action | String(10) | NOT NULL ('buy'/'sell') |
| quantity | Float | NOT NULL |
| fill_price | Float | nullable (null until filled) |
| status | String(20) | NOT NULL ('pending'/'filled'/'cancelled') |
| ordered_at | DateTime(tz=True) | NOT NULL |
| filled_at | DateTime(tz=True) | nullable |
| llm_decision_id | Integer | FK → llm_decisions.id, nullable |
| created_at | DateTime(tz=True) | NOT NULL |
| updated_at | DateTime(tz=True) | NOT NULL |

### Table: `positions`
| Column | Type | Constraints |
|--------|------|-------------|
| id | Integer | PK |
| instrument_id | Integer | FK → instruments.id, NOT NULL, unique |
| quantity | Float | NOT NULL |
| avg_entry_price | Float | NOT NULL |
| current_price | Float | nullable |
| unrealized_pnl | Float | nullable |
| last_updated | DateTime(tz=True) | NOT NULL |
| created_at | DateTime(tz=True) | NOT NULL |
| updated_at | DateTime(tz=True) | NOT NULL |

**Unique constraint:** `instrument_id` — one position row per symbol (upserted).

### Table: `portfolio_snapshots`
| Column | Type | Constraints |
|--------|------|-------------|
| id | Integer | PK |
| snapshot_at | DateTime(tz=True) | NOT NULL |
| total_value | Float | NOT NULL |
| cash | Float | NOT NULL |
| equity_value | Float | NOT NULL |
| daily_pnl | Float | nullable |
| total_pnl | Float | nullable |
| created_at | DateTime(tz=True) | NOT NULL |
| updated_at | DateTime(tz=True) | NOT NULL |

**Index:** `Index("ix_portfolio_snapshots_at", "snapshot_at")` — time-series queries.

### Table: `backtest_runs`
| Column | Type | Constraints |
|--------|------|-------------|
| id | Integer | PK |
| run_name | String(200) | nullable |
| start_date | Date | NOT NULL |
| end_date | Date | NOT NULL |
| symbols | Text | NOT NULL (comma-separated or JSON) |
| model_version | String(50) | NOT NULL |
| prompt_version | String(50) | NOT NULL |
| total_return | Float | nullable |
| cagr | Float | nullable |
| sharpe_ratio | Float | nullable |
| max_drawdown | Float | nullable |
| win_rate | Float | nullable |
| avg_win | Float | nullable |
| avg_loss | Float | nullable |
| num_trades | Integer | nullable |
| status | String(20) | NOT NULL default 'pending' |
| error_message | Text | nullable |
| completed_at | DateTime(tz=True) | nullable |
| created_at | DateTime(tz=True) | NOT NULL |
| updated_at | DateTime(tz=True) | NOT NULL |

All metric columns individual typed fields (D-12). [VERIFIED: locked decision]

## Common Pitfalls

### Pitfall 1: Missing `timeframe` column in `price_bars`
**What goes wrong:** `market_simulator.py` line 181 executes `pb.timeframe = :tf` — if the column is missing, `alembic upgrade head` succeeds but the first call to `MarketSimulator._db_bars()` raises `ProgrammingError: column "timeframe" does not exist`.
**Why it happens:** The column is not mentioned in the CONTEXT.md locked decisions (only inferred from reading the raw SQL). Easy to miss if only scanning the `Bar` dataclass.
**How to avoid:** Always include `timeframe String(10) NOT NULL default '1d'` in `price_bars`. [VERIFIED: read from market_simulator.py:181]
**Warning signs:** `ProgrammingError` mentioning `timeframe` on first `get_bars()` call with a DB session.

### Pitfall 2: `Base` defined in `models/` instead of `db/`
**What goes wrong:** Circular import — `alembic/env.py` imports from `app.models` which imports `Base` which imports back from `alembic/env.py`. Results in `ImportError` when running any migration.
**Why it happens:** Natural to put everything in `models/` but the base class must be in a dependency-free module.
**How to avoid:** `Base` lives exclusively in `backend/app/db/base.py`. All model files `from app.db.base import Base`.
**Warning signs:** `ImportError` or `AttributeError: module 'app.models' has no attribute 'Base'` on `alembic upgrade`.

### Pitfall 3: `target_metadata = None` left in env.py
**What goes wrong:** Autogenerate runs but detects 0 tables. Migration file is empty. Applying it does nothing — schema tables never get created.
**Why it happens:** The Alembic-generated `env.py` ships with `target_metadata = None` and a comment to replace it. Easy to overlook.
**How to avoid:** In `env.py`, set: `from app.db.base import Base; import app.models; target_metadata = Base.metadata`.
**Warning signs:** `alembic revision --autogenerate` produces a migration with empty `upgrade()` body.

### Pitfall 4: Timezone-naive datetimes in `price_bars`
**What goes wrong:** `market_simulator.py:189` passes `pd.Timestamp(from_date, tz="UTC")` to the query. If the `timestamp` column is timezone-naive, PostgreSQL raises `can't compare offset-naive and offset-aware datetimes`.
**Why it happens:** `DateTime` without `timezone=True` stores naive values; `DateTime(timezone=True)` stores TIMESTAMPTZ.
**How to avoid:** Use `mapped_column(DateTime(timezone=True))` for all datetime columns in `price_bars`, and `server_default=func.now()` in TimestampMixin always yields tz-aware.
**Warning signs:** `DataError` or `TypeError` on the first insert or query through the DB replay path.

### Pitfall 5: `alembic.ini` DATABASE_URL committed to git
**What goes wrong:** Real DB credentials end up in version control via `alembic.ini`.
**Why it happens:** Default template writes `sqlalchemy.url = driver://user:pass@localhost/dbname`.
**How to avoid:** In `env.py`, override the URL from environment: `config.set_main_option("sqlalchemy.url", os.environ.get("DATABASE_URL", ""))` and leave `sqlalchemy.url = ` (blank) in `alembic.ini`. Never populate `alembic.ini` with real credentials.
**Warning signs:** `git diff` shows a real URL in `alembic.ini`.

### Pitfall 6: Python 3.14 `from __future__ import annotations` + `Mapped` interaction
**What goes wrong:** In Python 3.14, `from __future__ import annotations` makes ALL annotations strings at parse time. SQLAlchemy 2.0.x evaluates `Mapped[T]` annotations at class creation — if they become strings, the ORM may fail to resolve the types.
**Why it happens:** SQLAlchemy 2.0 specifically handles `from __future__ import annotations` for `Mapped` types, but this interaction has edge cases with complex generics.
**How to avoid:** SQLAlchemy 2.0.x has explicit support for PEP 563 (`from __future__ import annotations`) in declarative models. Keep the import (project convention) but test that model imports succeed on Python 3.14 before proceeding. [ASSUMED — based on known SQLAlchemy 2.0 PEP 563 behavior; verify at runtime]
**Warning signs:** `TypeError: 'str' object is not a type` during model class creation.

## Code Examples

Verified patterns from official sources:

### TimestampMixin (SQLAlchemy 2.x)
```python
# Source: https://docs.sqlalchemy.org/en/20/orm/declarative_mixins.html
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
```

### Alembic op.bulk_insert
```python
# Source: https://alembic.sqlalchemy.org/en/latest/ops.html
from alembic import op
from sqlalchemy import Boolean, String, column, table


def upgrade() -> None:
    instruments_table = table(
        "instruments",
        column("symbol", String),
        column("name", String),
        column("asset_class", String),
        column("is_active", Boolean),
    )
    op.bulk_insert(
        instruments_table,
        [
            {"symbol": "AAPL", "name": "Apple Inc.", "asset_class": "equity", "is_active": True},
            # ... 7 more rows
        ],
    )
```

### FastAPI get_db dependency (sync)
```python
# Source: FastAPI SQL databases tutorial (sync variant)
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

### pg_dump schema export
```bash
# Run after alembic upgrade head
# Requires pg_dump on PATH (install: brew install postgresql@16 --client-only or Docker)
pg_dump \
  --schema-only \
  --no-owner \
  --no-acl \
  "$DATABASE_URL" \
  > database/schema.sql
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `declarative_base()` function | `class Base(DeclarativeBase)` | SQLAlchemy 2.0 (2023) | Old function still works but is legacy; new style gives better type inference |
| `Column(String, ...)` | `mapped_column(String, ...)` with `Mapped[T]` | SQLAlchemy 2.0 (2023) | Type annotations give IDE completion and mypy support |
| `relationship("ModelName")` string ref | `relationship()` with `Mapped["ModelName"]` annotation | SQLAlchemy 2.0 (2023) | Forward ref resolution improved |
| `@app.on_event("startup")` | `@asynccontextmanager lifespan(app)` | FastAPI 0.93+ (2023) | `on_event` deprecated; lifespan is the current pattern |

**Deprecated/outdated:**
- `declarative_base()`: Still works in SQLAlchemy 2.x but triggers `LegacyAPIWarning`. Do not use for new code.
- `Column()` in declarative: Still functional but not idiomatic in SQLAlchemy 2.x. Use `mapped_column()`.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `news_articles`, `ml_signals`, `trades`, `positions`, `portfolio_snapshots`, `backtest_runs` column schemas (beyond what is in CONTEXT.md) are based on project plan.md and standard domain knowledge | Exact 9-Table Schema | Columns may need adjustment in later phases — low risk since these tables have no existing consumers yet |
| A2 | FastAPI sync `get_db()` pattern is deadlock-safe for single-operator single-worker deployment | Standard Stack | True for single worker; would need async migration for multi-worker production — acceptable given single-operator scope |
| A3 | Python 3.14 + `from __future__ import annotations` + SQLAlchemy 2.0.51 `Mapped` works without issues | Common Pitfalls | If SQLAlchemy 2.0.51 has a bug with Python 3.14 annotation evaluation, model imports will fail at startup |
| A4 | `pg_dump` is available after installing PostgreSQL (via Docker or Homebrew) | Environment Availability | If Postgres not installed locally, pg_dump unavailable until Docker is set up — workaround is to defer schema.sql export to when Docker is available |
| A5 | `instruments.name` values in seed migration are reasonable display names | Code Examples | Minor cosmetic issue only |

## Open Questions

1. **pg_dump availability**
   - What we know: `pg_dump` is NOT on PATH locally (confirmed via `which pg_dump` check). PostgreSQL is not running locally.
   - What's unclear: Whether the developer will use Docker Postgres or install Postgres directly for this phase.
   - Recommendation: The plan should include a task to start Postgres (Docker: `docker run -e POSTGRES_PASSWORD=pw -p 5432:5432 postgres:16`) and note that the `pg_dump` step runs after `alembic upgrade head`. The schema.sql export can be completed as soon as any Postgres instance is reachable.

2. **`Mapped[Optional[float]]` vs `Mapped[float | None]` syntax**
   - What we know: Both work in SQLAlchemy 2.x. Project convention uses `from __future__ import annotations` and PEP 604 `X | None` syntax.
   - What's unclear: Which form is used for nullable mapped columns in this codebase (no existing ORM models yet).
   - Recommendation: Use `Optional[float]` from `typing` for nullable columns to maintain compatibility — `float | None` with `from __future__ import annotations` requires SQLAlchemy to evaluate the annotation string at runtime, which works in 2.0.51 but is slightly more fragile.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.14.0 | All backend code | ✓ | 3.14.0 | — |
| SQLAlchemy | ORM models | ✓ | 2.0.51 | — |
| Alembic | Migrations | ✓ | 1.18.4 | — |
| psycopg2-binary | PostgreSQL driver | ✓ | 2.9.12 | — |
| PostgreSQL (server) | DB to migrate | ✗ | — | Docker: `docker run -p 5432:5432 postgres:16` |
| pg_dump | schema.sql export | ✗ | — | Docker exec: `docker exec <container> pg_dump ...` |

**Missing dependencies with no fallback:**
- None — all missing items have Docker fallbacks.

**Missing dependencies with fallback:**
- PostgreSQL server: Not installed locally. Docker is the recommended path. Schema.sql export requires a running Postgres + pg_dump accessible from the container.
- pg_dump: Can run inside the Postgres Docker container via `docker exec`.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x (in requirements.txt) |
| Config file | none detected — Wave 0 must create `pytest.ini` or `pyproject.toml [tool.pytest]` |
| Quick run command | `pytest tests/ -x -q` |
| Full suite command | `pytest tests/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DATA-01 | All 9 tables created in DB with correct columns and indexes | integration | `pytest tests/test_models.py -x` | ❌ Wave 0 |
| DATA-01 | TimestampMixin `created_at`/`updated_at` present on all models | unit | `pytest tests/test_models.py::test_timestamp_mixin -x` | ❌ Wave 0 |
| DATA-01 | `llm_decisions` unique index enforced (duplicate insert raises IntegrityError) | integration | `pytest tests/test_models.py::test_llm_decision_unique_constraint -x` | ❌ Wave 0 |
| DATA-01 | `price_bars` composite index exists and query uses it | integration | `pytest tests/test_models.py::test_price_bars_index -x` | ❌ Wave 0 |
| DATA-02 | `alembic upgrade head` runs without errors on fresh DB | integration | `pytest tests/test_migrations.py -x` | ❌ Wave 0 |
| DATA-02 | Seed migration inserts exactly 8 instruments | integration | `pytest tests/test_migrations.py::test_seed_instruments -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/ -x -q`
- **Per wave merge:** `pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_models.py` — covers DATA-01 model column and constraint verification
- [ ] `tests/test_migrations.py` — covers DATA-02 alembic upgrade + seed data
- [ ] `tests/conftest.py` — shared SQLite or test-Postgres session fixture
- [ ] `pytest.ini` or `pyproject.toml [tool.pytest.ini_options]` — test configuration

**Note on test DB:** For Phase 1 model tests, use an in-memory SQLite engine (`sqlite:///:memory:`) via `Base.metadata.create_all(engine)` for unit/model tests. Migration tests require a real Postgres instance (Docker). Tests should gracefully skip migration tests if `TEST_DATABASE_URL` env var is absent.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Not applicable — schema phase only |
| V3 Session Management | no | Not applicable |
| V4 Access Control | no | Not applicable |
| V5 Input Validation | yes (low risk in Phase 1) | Pydantic validates data before ORM insert (Phase 3+) |
| V6 Cryptography | no | Not applicable |
| V8 Data Protection | yes | No PII in schema; market data and trade data only |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via raw `text()` queries | Tampering | `market_simulator.py` already uses parameterized `:ticker` etc. — maintain this pattern; never f-string SQL |
| DB credentials in alembic.ini | Information Disclosure | Override URL from `os.environ["DATABASE_URL"]` in env.py; never populate alembic.ini with real URL |
| Schema drift (models vs DB out of sync) | Tampering | Alembic tracks revisions; `alembic check` detects unapplied migrations |

## Project Constraints (from CLAUDE.md)

- **Paper trading only:** `ALPACA_BASE_URL` assertion not relevant to Phase 1 (no executor code).
- **No secrets in git:** `alembic.ini` must NOT contain real `DATABASE_URL`. Override from env in `env.py`.
- **`from __future__ import annotations`:** Required at top of every module per project convention.
- **Naming:** `snake_case.py` files, `PascalCase` classes, `snake_case` methods. Model files: `market_data.py`, `ml.py`, `trading.py`, `backtest.py`.
- **Sync session:** `AsyncSession` must NOT be used (D-02 locked decision).
- **No lookahead:** Not relevant to Phase 1 schema — but `news_articles.published_at` index must support `<= as_of_date` queries for Phase 4-6.
- **Test before marking done:** `pytest tests/` must pass before any checklist item is checked in `planning/plan.md`.

## Sources

### Primary (MEDIUM confidence — Context7/Official docs)
- [SQLAlchemy 2.0 Declarative Mixins](https://docs.sqlalchemy.org/en/20/orm/declarative_mixins.html) — TimestampMixin pattern with DeclarativeBase
- [SQLAlchemy 2.0 ORM Quick Start](https://docs.sqlalchemy.org/en/20/orm/quickstart.html) — DeclarativeBase + mapped_column complete example
- [SQLAlchemy 2.0 Declarative Tables](https://docs.sqlalchemy.org/en/20/orm/declarative_tables.html) — mapped_column, ForeignKey, Index, UniqueConstraint
- [Alembic 1.18.4 Tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html) — init, env.py, upgrade head
- [Alembic 1.18.4 Autogenerate](https://alembic.sqlalchemy.org/en/latest/autogenerate.html) — target_metadata, env.py configuration
- [Alembic 1.18.4 Operation Reference](https://alembic.sqlalchemy.org/en/latest/ops.html) — op.bulk_insert

### Secondary (MEDIUM confidence — verified against installed versions)
- `pip show sqlalchemy` → 2.0.51 [VERIFIED]
- `pip show alembic` → 1.18.4 [VERIFIED]
- `pip show psycopg2-binary` → 2.9.12 [VERIFIED]
- `market_simulator.py:177-184` raw SQL — exact column names for price_bars [VERIFIED: read from file]
- `market_interface.py:21-32` Bar dataclass — OHLCV field names [VERIFIED: read from file]

### Tertiary (LOW confidence — web search)
- [psycopg2-binary PyPI page](https://pypi.org/project/psycopg2-binary/) — Python 3.14 wheel availability confirmed for 2.9.12
- FastAPI SQLAlchemy sync session pattern — standard pattern documented in FastAPI tutorials

## Metadata

**Confidence breakdown:**
- Standard stack: MEDIUM — all packages verified via `pip show`; versions confirmed
- Schema design: HIGH — 2 of 9 tables directly verified from existing code; 7 tables use standard domain model patterns consistent with the plan
- Architecture patterns: MEDIUM — SQLAlchemy 2.x and Alembic patterns verified from official docs
- Pitfalls: HIGH — most derived from direct code inspection (timeframe column, Base import order) plus well-known SQLAlchemy/Alembic gotchas

**Research date:** 2026-06-25
**Valid until:** 2026-09-25 (SQLAlchemy 2.0 and Alembic 1.x are stable; psycopg2-binary Python 3.14 support is new and worth rechecking if installation issues arise)
