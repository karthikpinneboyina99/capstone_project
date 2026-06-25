from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class MLSignal(Base, TimestampMixin):
    __tablename__ = "ml_signals"
    __table_args__ = (
        Index("ix_ml_signal_instrument_date", "instrument_id", "as_of_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    signal_score: Mapped[float] = mapped_column(Float, nullable=False)
    features_used: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    instrument = relationship("Instrument", back_populates="ml_signals")
    llm_decisions = relationship("LLMDecision", back_populates="ml_signal")
