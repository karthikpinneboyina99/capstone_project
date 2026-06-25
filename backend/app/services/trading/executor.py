"""
Live paper-trading executor.

Entry point: run_daily_cycle(db)
Called by APScheduler at 9:35 AM ET on trading days.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Instrument, MLSignal, PortfolioSnapshot, Position, Trade
from app.services.trading.alpaca_client import AlpacaPaperClient
from app.services.data_ingestion.alpaca_loader import fetch_latest_bars
from app.services.ml.predict import predict as ml_predict
from app.services.llm_reasoning.decision_engine import get_or_create_decision

logger = logging.getLogger(__name__)


def _get_or_create_instrument(db: Session, symbol: str) -> Instrument:
    inst = db.query(Instrument).filter(Instrument.symbol == symbol).first()
    if inst is None:
        inst = Instrument(symbol=symbol, is_active=True)
        db.add(inst)
        db.flush()
    return inst


def _get_open_position(db: Session, instrument_id: int) -> Position | None:
    return (
        db.query(Position)
        .filter(
            Position.instrument_id == instrument_id,
            Position.mode == "paper",
            Position.backtest_run_id == None,  # noqa: E711
            Position.quantity > 0,
        )
        .first()
    )


def _open_position_count(db: Session) -> int:
    return (
        db.query(Position)
        .filter(
            Position.mode == "paper",
            Position.backtest_run_id == None,  # noqa: E711
            Position.quantity > 0,
        )
        .count()
    )


def _load_price_dfs(db: Session, symbols: list[str], lookback_days: int = 60) -> dict[str, pd.DataFrame]:
    """
    Load price DataFrames from the DB via the market data provider.
    Falls back to an empty dict on error (per-symbol errors handled inside provider).
    Returns dict symbol -> DataFrame with columns including 'close'.
    """
    from app.services.data_ingestion.market_interface import create_provider  # local import avoids circular dep

    today = date.today()
    from_date = today - timedelta(days=lookback_days + 5)  # buffer for weekends/holidays

    provider = create_provider(db_session=db)
    try:
        dfs = provider.get_bars(symbols, from_date, today)
    except Exception as exc:
        logger.error("Failed to load price DataFrames: %s", exc)
        return {}

    # Normalise: provider returns DataFrames with a 'date' column; ml predict
    # needs a 'close' column. Rename 'date' → set as index if the feature
    # engineer expects a DatetimeIndex, but we keep the column form and
    # just ensure 'close' is present.
    result: dict[str, pd.DataFrame] = {}
    for sym, df in dfs.items():
        if df is None or df.empty:
            continue
        result[sym] = df
    return result


def run_daily_cycle(db: Session) -> dict:
    """
    Run one daily paper-trading cycle.
    Returns a summary dict for logging/debugging.
    """
    today = date.today()
    logger.info("Daily paper-trading cycle starting for %s", today)

    client = AlpacaPaperClient()

    # ── 1. Account state ──────────────────────────────────────────────────────
    account = client.get_account()
    cash = account["cash"]
    portfolio_value = account["portfolio_value"]
    equity = account["equity"]

    # ── 2. Daily loss circuit breaker ─────────────────────────────────────────
    yesterday = (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.mode == "paper",
            PortfolioSnapshot.backtest_run_id == None,  # noqa: E711
        )
        .order_by(PortfolioSnapshot.as_of_date.desc())
        .first()
    )
    if yesterday is not None:
        day_loss_pct = (portfolio_value - float(yesterday.total_value)) / float(yesterday.total_value)
        if day_loss_pct < -settings.DAILY_LOSS_LIMIT_PCT:
            logger.warning(
                "Daily loss circuit breaker triggered: %.2f%% loss (limit %.2f%%)",
                day_loss_pct * 100,
                settings.DAILY_LOSS_LIMIT_PCT * 100,
            )
            _record_snapshot(db, today, cash, equity, portfolio_value)
            db.commit()
            return {"status": "circuit_breaker", "day_loss_pct": day_loss_pct}

    # ── 3. Fetch latest price data (Alpaca if configured, else yfinance) ─────────
    _alpaca_key = settings.ALPACA_API_KEY or ""
    _no_alpaca = _alpaca_key in {"", "your_alpaca_paper_key_id"}
    if not _no_alpaca:
        try:
            fetch_latest_bars(db, symbols=settings.WATCHLIST, lookback_days=60)
        except Exception as exc:
            logger.error("Failed to ingest price data from Alpaca: %s", exc)
    else:
        # Fall back to yfinance for price ingestion (simulation mode)
        try:
            from app.services.data_ingestion.yfinance_loader import fetch_and_store
            from datetime import timedelta
            fetch_and_store(
                db,
                symbols=settings.WATCHLIST,
                start=today - timedelta(days=90),
                end=today,
            )
        except Exception as exc:
            logger.error("yfinance fallback ingestion failed: %s", exc)

    price_dfs = _load_price_dfs(db, symbols=settings.WATCHLIST, lookback_days=60)

    # ── 4. Signal + decision loop ─────────────────────────────────────────────
    orders_placed = []
    open_count = _open_position_count(db)

    for symbol in settings.WATCHLIST:
        try:
            _process_symbol(
                db=db,
                client=client,
                symbol=symbol,
                price_dfs=price_dfs,
                today=today,
                portfolio_value=portfolio_value,
                cash=cash,
                open_count=open_count,
                orders_placed=orders_placed,
            )
        except Exception as exc:
            logger.error("Error processing %s: %s", symbol, exc)
            continue

    # ── 5. Record portfolio snapshot ──────────────────────────────────────────
    # Re-fetch account after orders
    try:
        account = client.get_account()
        cash = account["cash"]
        portfolio_value = account["portfolio_value"]
        equity = account["equity"]
    except Exception:
        pass

    _record_snapshot(db, today, cash, equity, portfolio_value)
    db.commit()

    logger.info(
        "Daily cycle complete — %d orders placed, portfolio_value=%.2f",
        len(orders_placed),
        portfolio_value,
    )
    return {
        "status": "ok",
        "date": today.isoformat(),
        "orders_placed": len(orders_placed),
        "portfolio_value": portfolio_value,
    }


def _last_close(price_df: pd.DataFrame) -> float:
    """Extract the last closing price from a DataFrame returned by the market provider."""
    for col in ("close", "Close"):
        if col in price_df.columns:
            val = price_df[col].iloc[-1]
            return float(val) if pd.notna(val) else 0.0
    return 0.0


def _process_symbol(
    db: Session,
    client: AlpacaPaperClient,
    symbol: str,
    price_dfs: dict,
    today: date,
    portfolio_value: float,
    cash: float,
    open_count: int,
    orders_placed: list,
) -> None:
    """Process one symbol: signal → decision → order."""
    inst = _get_or_create_instrument(db, symbol)
    price_df = price_dfs.get(symbol)

    # ── ML signal ──────────────────────────────────────────────────────────────
    if price_df is None or len(price_df) < 30:
        logger.debug("Not enough price data for %s", symbol)
        return

    ml_result = ml_predict(symbol, price_df, today)
    signal_score = ml_result["signal_score"]

    # Persist MLSignal
    sig = MLSignal(
        instrument_id=inst.id,
        as_of_date=today,
        model_version=ml_result.get("model_version", "xgb_v1"),
        signal_score=signal_score,
        features_used=ml_result.get("features_snapshot"),
    )
    db.add(sig)
    db.flush()

    # ── LLM decision ───────────────────────────────────────────────────────────
    decision = get_or_create_decision(
        db=db,
        instrument_id=inst.id,
        as_of_date=today,
        ml_signal=sig,
        price_df=price_df,
        portfolio_value=portfolio_value,
    )

    action = decision.action
    pos_size_pct = decision.position_size_pct or 0.0
    existing_pos = _get_open_position(db, inst.id)
    last_close = _last_close(price_df)

    # ── Risk checks + order placement ──────────────────────────────────────────
    if action == "buy":
        if open_count >= settings.MAX_POSITIONS and existing_pos is None:
            logger.debug(
                "MAX_POSITIONS (%d) reached, skipping buy for %s",
                settings.MAX_POSITIONS,
                symbol,
            )
            return
        target_notional = portfolio_value * settings.MAX_POSITION_PCT * pos_size_pct
        if target_notional < 1.0:
            return
        target_notional = min(target_notional, cash * 0.99)
        order = client.submit_market_buy(symbol, target_notional)
        if order:
            qty = target_notional / last_close if last_close > 0 else 0.0
            trade = Trade(
                instrument_id=inst.id,
                decision_id=decision.id,
                side="buy",
                quantity=qty,
                price=last_close,
                executed_at=datetime.now(tz=timezone.utc),
                mode="paper",
                alpaca_order_id=str(order.get("id", "")),
            )
            db.add(trade)
            _upsert_position(db, inst.id, qty, last_close, existing_pos)
            orders_placed.append({"symbol": symbol, "side": "buy", "notional": target_notional})
            if existing_pos is None:
                open_count += 1

    elif action == "sell" and existing_pos is not None:
        qty_to_sell = existing_pos.quantity
        order = client.submit_market_sell(symbol, qty_to_sell)
        if order:
            trade = Trade(
                instrument_id=inst.id,
                decision_id=decision.id,
                side="sell",
                quantity=qty_to_sell,
                price=last_close,
                executed_at=datetime.now(tz=timezone.utc),
                mode="paper",
                alpaca_order_id=str(order.get("id", "")),
            )
            db.add(trade)
            existing_pos.quantity = 0
            orders_placed.append({"symbol": symbol, "side": "sell", "qty": qty_to_sell})


def _upsert_position(
    db: Session,
    instrument_id: int,
    qty: float,
    price: float,
    existing: Position | None,
) -> None:
    if existing is None:
        pos = Position(
            instrument_id=instrument_id,
            quantity=qty,
            avg_entry_price=price,
            mode="paper",
        )
        db.add(pos)
    else:
        total_cost = existing.avg_entry_price * existing.quantity + price * qty
        existing.quantity += qty
        existing.avg_entry_price = total_cost / existing.quantity if existing.quantity > 0 else 0


def _record_snapshot(
    db: Session, today: date, cash: float, equity: float, total_value: float
) -> None:
    snap = PortfolioSnapshot(
        as_of_date=today,
        mode="paper",
        cash=cash,
        equity=equity,
        total_value=total_value,
    )
    db.add(snap)
