"""
Assembles the natural-language context payload fed into the LLM prompt.

All data is as-of `as_of_date` — no future information is included.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd
from sqlalchemy.orm import Session

from app.models import Instrument, NewsArticle, Position

logger = logging.getLogger(__name__)


def build_context(
    db: Session,
    symbol: str,
    as_of_date: date,
    signal_score: float,
    features_snapshot: dict | None,
    price_df: pd.DataFrame | None,
    portfolio_value: float = 100_000.0,
    max_position_pct: float = 0.10,
) -> dict:
    """
    Build the context dict that is injected into the LLM prompt.

    Returns a dict with keys:
      symbol, as_of_date, signal_score, top_features,
      price_summary, news_headlines, current_position,
      portfolio_value, max_position_pct
    """
    # ── Price action summary ──────────────────────────────────────────────────
    price_summary = _build_price_summary(price_df, as_of_date)

    # ── Top contributing features ─────────────────────────────────────────────
    top_features = _top_features(features_snapshot)

    # ── News headlines (most recent 5, published_at <= as_of_date) ───────────
    news_headlines = _get_news(db, symbol, as_of_date)

    # ── Current position ──────────────────────────────────────────────────────
    current_position = _get_position(db, symbol)

    return {
        "symbol": symbol,
        "as_of_date": as_of_date.isoformat(),
        "signal_score": round(signal_score, 4),
        "signal_direction": "bullish" if signal_score > 0.1 else "bearish" if signal_score < -0.1 else "neutral",
        "top_features": top_features,
        "price_summary": price_summary,
        "news_headlines": news_headlines,
        "current_position": current_position,
        "portfolio_value": portfolio_value,
        "max_position_pct": max_position_pct,
        "max_position_dollars": round(portfolio_value * max_position_pct, 2),
    }


def _build_price_summary(price_df: pd.DataFrame | None, as_of_date: date) -> str:
    if price_df is None or price_df.empty:
        return "No recent price data available."

    df = price_df.copy()
    if "close" not in df.columns:
        df.columns = [c.lower() for c in df.columns]

    # Use only data up to as_of_date
    if hasattr(df.index, "date"):
        df = df[df.index.date <= as_of_date]
    elif "date" in df.columns:
        df = df[df["date"] <= as_of_date]

    if df.empty:
        return "No recent price data available."

    recent = df.tail(10)
    last_close = float(recent["close"].iloc[-1])
    ret_5d = (last_close / float(recent["close"].iloc[max(-5, -len(recent))]) - 1) * 100
    ret_20d_idx = max(-20, -len(df))
    ret_20d = (last_close / float(df["close"].iloc[ret_20d_idx]) - 1) * 100
    high_20d = float(df["high"].tail(20).max()) if "high" in df.columns else last_close
    low_20d = float(df["low"].tail(20).min()) if "low" in df.columns else last_close

    return (
        f"Last close: ${last_close:.2f}. "
        f"5-day return: {ret_5d:+.1f}%. "
        f"20-day return: {ret_20d:+.1f}%. "
        f"20-day range: ${low_20d:.2f}–${high_20d:.2f}."
    )


def _top_features(features_snapshot: dict | None, top_n: int = 3) -> str:
    if not features_snapshot:
        return "Feature data not available."
    lines = []
    items = sorted(features_snapshot.items(), key=lambda x: abs(x[1]), reverse=True)[:top_n]
    for name, val in items:
        lines.append(f"{name}: {val:.4f}")
    return "; ".join(lines)


def _get_news(db: Session, symbol: str, as_of_date: date, limit: int = 5) -> list[str]:
    from datetime import datetime, timezone
    cutoff = datetime(as_of_date.year, as_of_date.month, as_of_date.day, 23, 59, 59)
    inst = db.query(Instrument).filter(Instrument.symbol == symbol).first()
    if inst is None:
        return []
    articles = (
        db.query(NewsArticle)
        .filter(
            NewsArticle.instrument_id == inst.id,
            NewsArticle.published_at <= cutoff,
        )
        .order_by(NewsArticle.published_at.desc())
        .limit(limit)
        .all()
    )
    return [f"[{a.published_at.date()}] {a.headline}" for a in articles]


def _get_position(db: Session, symbol: str) -> dict:
    inst = db.query(Instrument).filter(Instrument.symbol == symbol).first()
    if inst is None:
        return {"quantity": 0, "avg_entry_price": None}
    pos = (
        db.query(Position)
        .filter(
            Position.instrument_id == inst.id,
            Position.mode == "paper",
            Position.backtest_run_id == None,  # noqa: E711
            Position.quantity > 0,
        )
        .first()
    )
    if pos is None:
        return {"quantity": 0, "avg_entry_price": None}
    return {"quantity": pos.quantity, "avg_entry_price": pos.avg_entry_price}
