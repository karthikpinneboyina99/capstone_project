from datetime import date, datetime

from sqlalchemy import Date, DateTime, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class BacktestRun(Base, TimestampMixin):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    date_range_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_range_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    strategy_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # results stores: CAGR, Sharpe, max_drawdown, win_rate, num_trades, total_return, turnover
    results: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    trades = relationship("Trade", back_populates="backtest_run")
    positions = relationship("Position", back_populates="backtest_run")
    portfolio_snapshots = relationship("PortfolioSnapshot", back_populates="backtest_run")
