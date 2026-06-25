"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("name", sa.String(256), nullable=True),
        sa.Column("sector", sa.String(128), nullable=True),
        sa.Column("asset_class", sa.String(32), nullable=False, server_default="equity"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", name="uq_instrument_symbol"),
    )
    op.create_index("ix_instruments_symbol", "instruments", ["symbol"])

    op.create_table(
        "price_bars",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(12, 4), nullable=True),
        sa.Column("high", sa.Numeric(12, 4), nullable=True),
        sa.Column("low", sa.Numeric(12, 4), nullable=True),
        sa.Column("close", sa.Numeric(12, 4), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=True),
        sa.Column("timeframe", sa.String(8), nullable=False, server_default="1d"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "instrument_id", "timestamp", "timeframe", name="uq_price_bar"
        ),
    )
    op.create_index(
        "ix_price_bars_instrument_timestamp",
        "price_bars",
        ["instrument_id", "timestamp"],
    )

    op.create_table(
        "news_articles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("headline", sa.String(512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("source", sa.String(128), nullable=True),
        sa.Column("url", sa.String(1024), nullable=True),
        sa.Column("sentiment_score", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_news_instrument_published",
        "news_articles",
        ["instrument_id", "published_at"],
    )

    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("date_range_start", sa.Date(), nullable=True),
        sa.Column("date_range_end", sa.Date(), nullable=True),
        sa.Column("strategy_version", sa.String(64), nullable=True),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("results", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "ml_signals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("signal_score", sa.Float(), nullable=False),
        sa.Column("features_used", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ml_signal_instrument_date",
        "ml_signals",
        ["instrument_id", "as_of_date"],
    )

    op.create_table(
        "llm_decisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("ml_signal_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(8), nullable=False),
        sa.Column("position_size_pct", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("risk_flags", sa.JSON(), nullable=False),
        sa.Column("raw_response", sa.JSON(), nullable=True),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("model_slug", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.ForeignKeyConstraint(["ml_signal_id"], ["ml_signals.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "instrument_id",
            "as_of_date",
            "model_slug",
            "prompt_version",
            name="uq_decision_cache",
        ),
    )
    op.create_index(
        "ix_llm_decision_instrument_date",
        "llm_decisions",
        ["instrument_id", "as_of_date"],
    )

    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("decision_id", sa.Integer(), nullable=True),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("alpaca_order_id", sa.String(64), nullable=True),
        sa.Column("backtest_run_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["backtest_run_id"], ["backtest_runs.id"]),
        sa.ForeignKeyConstraint(["decision_id"], ["llm_decisions.id"]),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_trades_instrument_executed", "trades", ["instrument_id", "executed_at"]
    )
    op.create_index("ix_trades_mode_backtest", "trades", ["mode", "backtest_run_id"])

    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("avg_entry_price", sa.Float(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("backtest_run_id", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["backtest_run_id"], ["backtest_runs.id"]),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "instrument_id", "mode", "backtest_run_id", name="uq_position_backtest"
        ),
    )
    op.create_index("ix_positions_mode", "positions", ["mode"])
    # Partial unique index for paper-mode positions (backtest_run_id IS NULL)
    op.execute(
        "CREATE UNIQUE INDEX uq_position_paper ON positions (instrument_id, mode) "
        "WHERE backtest_run_id IS NULL"
    )

    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("cash", sa.Float(), nullable=False),
        sa.Column("equity", sa.Float(), nullable=False),
        sa.Column("total_value", sa.Float(), nullable=False),
        sa.Column("backtest_run_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["backtest_run_id"], ["backtest_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "as_of_date", "mode", "backtest_run_id", name="uq_snapshot"
        ),
    )
    op.create_index(
        "ix_snapshot_date_mode", "portfolio_snapshots", ["as_of_date", "mode"]
    )


def downgrade() -> None:
    op.drop_table("portfolio_snapshots")
    op.drop_table("positions")
    op.drop_table("trades")
    op.drop_table("llm_decisions")
    op.drop_table("ml_signals")
    op.drop_table("backtest_runs")
    op.drop_table("news_articles")
    op.drop_table("price_bars")
    op.drop_table("instruments")
