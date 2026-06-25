# Phase 1: Database and Models - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-25
**Phase:** 1-Database-and-Models
**Areas discussed:** TimescaleDB vs plain Postgres, Model file layout, Instruments seeding, SQLAlchemy sync vs async

---

## TimescaleDB vs plain Postgres

| Option | Description | Selected |
|--------|-------------|----------|
| Plain PostgreSQL | Composite index on (instrument_id, timestamp). Works everywhere. | ✓ |
| TimescaleDB extension | Hypertable partitioned by timestamp. Adds extension overhead. | |

**User's choice:** Plain PostgreSQL
**Notes:** With ~20K rows max (5-15 symbols × 5yr × 252 days), TimescaleDB optimization is unnecessary. Prefer deploy-platform compatibility.

---

## Model file layout

| Option | Description | Selected |
|--------|-------------|----------|
| Domain-grouped files | market_data.py, ml.py, trading.py, backtest.py | ✓ |
| One file per table | 9 separate files | |
| Single models.py | All in one file | |

**User's choice:** Domain-grouped files

| Option | Description | Selected |
|--------|-------------|----------|
| Re-export from __init__.py | `from app.models import Instrument` everywhere | ✓ |
| Direct file imports | `from app.models.market_data import Instrument` | |

**User's choice:** Re-export from `__init__.py`
**Notes:** Clean single import point for all downstream service layers.

---

## Instruments seeding

| Option | Description | Selected |
|--------|-------------|----------|
| Alembic seed migration | op.bulk_insert() in migration 02 | ✓ |
| Separate seed script | backend/scripts/seed_instruments.py | |
| Manual SQL in README | Document INSERT statements | |

**User's choice:** Alembic seed migration

**Symbol selection:** Deferred to Claude.
**Notes:** Claude chose AAPL, MSFT, NVDA, GOOGL, AMZN, META, SPY, QQQ (8 symbols — Mag-7 tech + 2 index ETFs).

**Instruments columns:** Deferred to Claude.
**Notes:** Claude chose minimal set: id, symbol, name, asset_class, is_active + TimestampMixin.

---

## SQLAlchemy sync vs async

**Resolved autonomously (user enabled yolo mode mid-discussion):**
Sync `Session` chosen for consistency with the existing sync data_ingestion layer and simplicity for a single-operator capstone.

---

## Claude's Discretion

- Watchlist symbol set: AAPL, MSFT, NVDA, GOOGL, AMZN, META, SPY, QQQ
- `instruments` minimal column set
- SQLAlchemy sync vs async: sync Session
- `backtest_runs` metrics as individual typed columns (not JSONB)

## Deferred Ideas

None.
