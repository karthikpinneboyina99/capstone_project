from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class LLMDecision(Base, TimestampMixin):
    __tablename__ = "llm_decisions"
    __table_args__ = (
        # Decision cache key — unique on these four columns so re-running a backtest
        # never re-calls the LLM for dates already processed.
        UniqueConstraint(
            "instrument_id", "as_of_date", "model_slug", "prompt_version",
            name="uq_decision_cache",
        ),
        Index("ix_llm_decision_instrument_date", "instrument_id", "as_of_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    ml_signal_id: Mapped[int | None] = mapped_column(ForeignKey("ml_signals.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(8), nullable=False)  # buy | sell | hold
    position_size_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_flags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    raw_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False)
    model_slug: Mapped[str] = mapped_column(String(64), nullable=False)

    instrument = relationship("Instrument", back_populates="llm_decisions")
    ml_signal = relationship("MLSignal", back_populates="llm_decisions")
    trades = relationship("Trade", back_populates="decision")
