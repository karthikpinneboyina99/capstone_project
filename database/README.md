# database/

Schema definitions and migrations for the Postgres database (price bars, instruments, ML signals, LLM decisions, trades, positions, portfolio snapshots, backtest runs).

Full schema (table-by-table, with columns) is specified in `../planning/plan.md`, section "Database Schema". Use Alembic for migrations once the schema is finalized in Phase 1.

Expected structure:

```
database/
├── migrations/        # Alembic migration scripts
└── schema.sql          # Reference copy of the full schema (source of truth lives in models/)
```
