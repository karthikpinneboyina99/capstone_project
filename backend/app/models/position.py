from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        # Partial unique index is added in the Alembic migration:
        #   CREATE UNIQUE INDEX uq_position_paper ON positions (instrument_id, mode)
        #   WHERE backtest_run_id IS NULL;
        # For backtest rows the full (instrument_id, mode, backtest_run_id) triplet is unique.
        UniqueConstraint(
            "instrument_id", "mode", "backtest_run_id", name="uq_position_backtest"
        ),
        Index("ix_positions_mode", "mode"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    avg_entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)  # backtest | paper
    backtest_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("backtest_runs.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    instrument = relationship("Instrument", back_populates="positions")
    backtest_run = relationship("BacktestRun", back_populates="positions")
