from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "as_of_date", "mode", "backtest_run_id", name="uq_snapshot"
        ),
        Index("ix_snapshot_date_mode", "as_of_date", "mode"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)  # backtest | paper
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    equity: Mapped[float] = mapped_column(Float, nullable=False)
    total_value: Mapped[float] = mapped_column(Float, nullable=False)
    backtest_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("backtest_runs.id"), nullable=True
    )

    backtest_run = relationship("BacktestRun", back_populates="portfolio_snapshots")
