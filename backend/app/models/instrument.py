from sqlalchemy import Boolean, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Instrument(Base, TimestampMixin):
    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(128), nullable=True)
    asset_class: Mapped[str] = mapped_column(String(32), nullable=False, default="equity")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    price_bars = relationship("PriceBar", back_populates="instrument", lazy="dynamic")
    news_articles = relationship("NewsArticle", back_populates="instrument", lazy="dynamic")
    ml_signals = relationship("MLSignal", back_populates="instrument", lazy="dynamic")
    llm_decisions = relationship("LLMDecision", back_populates="instrument", lazy="dynamic")
    trades = relationship("Trade", back_populates="instrument", lazy="dynamic")
    positions = relationship("Position", back_populates="instrument")
