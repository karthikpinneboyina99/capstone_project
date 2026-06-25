from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Trade(Base, TimestampMixin):
    __tablename__ = "trades"
    __table_args__ = (
        Index("ix_trades_instrument_executed", "instrument_id", "executed_at"),
        Index("ix_trades_mode_backtest", "mode", "backtest_run_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    decision_id: Mapped[int | None] = mapped_column(ForeignKey("llm_decisions.id"), nullable=True)
    side: Mapped[str] = mapped_column(String(4), nullable=False)   # buy | sell
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)  # backtest | paper
    alpaca_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    backtest_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("backtest_runs.id"), nullable=True
    )

    instrument = relationship("Instrument", back_populates="trades")
    decision = relationship("LLMDecision", back_populates="trades")
    backtest_run = relationship("BacktestRun", back_populates="trades")
