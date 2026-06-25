"""
Event-driven day-by-day backtesting engine.

Loop per trading day D:
  1. Fill any pending orders at D's open (placed on D-1)
  2. Record portfolio snapshot
  3. Compute features for each symbol using data <= D
  4. Get ML signal (predict) — or use signal_override_fn for sanity checks
  5. Optionally get LLM decision (use_llm=True); otherwise use ML-only threshold rule
  6. Apply risk checks (MAX_POSITION_PCT, MAX_POSITIONS, DAILY_LOSS_LIMIT_PCT)
  7. Queue orders to fill at D+1 open (NO same-bar lookahead)

Produces a BacktestRun with results stored in the DB.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Callable, Optional

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    BacktestRun,
    Instrument,
    MLSignal,
    PortfolioSnapshot,
    Position,
    Trade,
)
from app.services.backtesting.metrics import compute_all_metrics

logger = logging.getLogger(__name__)

STARTING_CASH = 100_000.0


class _SimPosition:
    """In-memory position tracker during backtesting — not written to DB until end."""

    def __init__(self, symbol: str, instrument_id: int):
        self.symbol = symbol
        self.instrument_id = instrument_id
        self.quantity: float = 0.0
        self.avg_entry_price: float = 0.0

    @property
    def is_open(self) -> bool:
        return self.quantity > 0

    def update_on_buy(self, qty: float, price: float) -> None:
        total_cost = self.avg_entry_price * self.quantity + price * qty
        self.quantity += qty
        self.avg_entry_price = total_cost / self.quantity if self.quantity > 0 else 0.0

    def update_on_sell(self, qty: float) -> float:
        """Returns actual quantity sold (capped at held quantity)."""
        actual_qty = min(qty, self.quantity)
        self.quantity -= actual_qty
        if self.quantity == 0:
            self.avg_entry_price = 0.0
        return actual_qty


def run_backtest(
    db: Session,
    price_dfs: dict[str, pd.DataFrame],
    start_date: date,
    end_date: date,
    strategy_version: str = "v1",
    model_version: str = "xgb_v1",
    use_llm: bool = False,
    signal_override_fn: Optional[Callable] = None,
    params: dict | None = None,
) -> BacktestRun:
    """
    Run a full backtest and persist results.

    Args:
        db: SQLAlchemy session
        price_dfs: dict symbol -> price DataFrame (full history, sorted ascending by date).
                   Must have columns: open, high, low, close, volume (case-insensitive).
        start_date: first date to generate signals
        end_date: last date in backtest range (final snapshot — no fill queued after this day)
        strategy_version: label stored in backtest_run
        model_version: which ML model artifact to use
        use_llm: if True, call decision_engine for LLM decisions (slower, Cerebras rate-limited)
        signal_override_fn: optional callable(symbol: str, d: date) -> float to override ML
                            signals (used for the shuffle sanity check)
        params: arbitrary params dict stored in backtest_run

    Returns:
        Persisted BacktestRun ORM object with results populated.
    """
    # ── Create BacktestRun record ─────────────────────────────────────────────
    run = BacktestRun(
        started_at=datetime.now(tz=timezone.utc),
        date_range_start=start_date,
        date_range_end=end_date,
        strategy_version=strategy_version,
        params=params or {},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    logger.info("Backtest run %d started: %s -> %s", run.id, start_date, end_date)

    # ── Resolve / create Instrument rows ─────────────────────────────────────
    symbols = list(price_dfs.keys())
    instruments: dict[str, Instrument] = {}
    for sym in symbols:
        inst = db.query(Instrument).filter(Instrument.symbol == sym).first()
        if inst is None:
            inst = Instrument(symbol=sym, is_active=True)
            db.add(inst)
            db.flush()
        instruments[sym] = inst
    db.commit()

    # ── Build trading day calendar ────────────────────────────────────────────
    # Union of all available dates across all symbol DataFrames, filtered to [start, end]
    all_dates: set[date] = set()
    for df in price_dfs.values():
        idx = df.index
        if hasattr(idx, "date"):
            all_dates.update(d.date() for d in idx)
        else:
            all_dates.update(pd.Timestamp(d).date() if not isinstance(d, date) else d for d in idx)
    trading_days = sorted(d for d in all_dates if start_date <= d <= end_date)

    if len(trading_days) < 2:
        logger.warning("Not enough trading days in range %s-%s", start_date, end_date)
        run.finished_at = datetime.now(tz=timezone.utc)
        run.results = {}
        db.commit()
        return run

    # ── Simulation state ──────────────────────────────────────────────────────
    cash = STARTING_CASH
    positions: dict[str, _SimPosition] = {
        sym: _SimPosition(sym, instruments[sym].id) for sym in symbols
    }
    # Orders queued on day D for fill at D+1 open
    pending_orders: list[dict] = []

    # Accumulated data lists (bulk-written at end)
    all_trades: list[dict] = []      # lightweight dicts for metrics only
    db_trades: list[Trade] = []
    db_snapshots: list[PortfolioSnapshot] = []

    # ── Helper: look up a single price value ─────────────────────────────────
    def _get_price(sym: str, d: date, col: str) -> float | None:
        df = price_dfs.get(sym)
        if df is None:
            return None
        # Support both DatetimeIndex and plain date index
        if hasattr(df.index, "date"):
            rows = df[df.index.date == d]
        else:
            rows = df[df.index == d]
        if rows.empty:
            return None
        # Accept 'close'/'Close', 'open'/'Open', etc.
        for candidate in (col.lower(), col.capitalize()):
            if candidate in rows.columns:
                val = rows[candidate].iloc[-1]
                return float(val) if pd.notna(val) else None
        return None

    def _portfolio_equity(d: date) -> float:
        eq = 0.0
        for sym, pos in positions.items():
            if pos.is_open:
                price = _get_price(sym, d, "close") or pos.avg_entry_price
                eq += pos.quantity * price
        return eq

    # ── Main loop ─────────────────────────────────────────────────────────────
    equity_series: list[tuple[date, float]] = []

    for i, today in enumerate(trading_days):
        next_day = trading_days[i + 1] if i + 1 < len(trading_days) else None

        # ── Step 1: Fill pending orders at today's open ───────────────────────
        for order in pending_orders:
            sym = order["symbol"]
            fill_price = _get_price(sym, today, "open")
            if fill_price is None or fill_price <= 0:
                logger.debug("No open price for %s on %s — skipping fill", sym, today)
                continue

            ts = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)

            if order["side"] == "buy":
                max_spend = min(order["target_spend"], cash)
                qty = max_spend / fill_price
                if qty <= 0:
                    continue
                cash -= qty * fill_price
                positions[sym].update_on_buy(qty, fill_price)
                all_trades.append({"symbol": sym, "side": "buy", "quantity": qty,
                                   "price": fill_price, "date": today, "pnl": None})
                db_trades.append(Trade(
                    instrument_id=instruments[sym].id,
                    decision_id=order.get("decision_id"),
                    side="buy",
                    quantity=qty,
                    price=fill_price,
                    executed_at=ts,
                    mode="backtest",
                    backtest_run_id=run.id,
                ))

            elif order["side"] == "sell":
                qty = positions[sym].update_on_sell(order["quantity"])
                if qty <= 0:
                    continue
                proceeds = qty * fill_price
                cash += proceeds
                pnl = (fill_price - order.get("avg_entry_price", fill_price)) * qty
                all_trades.append({"symbol": sym, "side": "sell", "quantity": qty,
                                   "price": fill_price, "date": today, "pnl": pnl})
                db_trades.append(Trade(
                    instrument_id=instruments[sym].id,
                    decision_id=order.get("decision_id"),
                    side="sell",
                    quantity=qty,
                    price=fill_price,
                    executed_at=ts,
                    mode="backtest",
                    backtest_run_id=run.id,
                ))

        pending_orders = []

        # ── Step 2: Record portfolio snapshot ────────────────────────────────
        equity = _portfolio_equity(today)
        total_val = cash + equity
        db_snapshots.append(PortfolioSnapshot(
            as_of_date=today,
            mode="backtest",
            cash=cash,
            equity=equity,
            total_value=total_val,
            backtest_run_id=run.id,
        ))
        equity_series.append((today, total_val))

        # ── Step 3: No signal generation on the last day (nothing to fill) ───
        if next_day is None:
            continue

        # ── Step 4: Daily loss circuit breaker ───────────────────────────────
        if len(equity_series) > 1:
            prev_val = equity_series[-2][1]
            if prev_val > 0:
                day_loss_pct = (total_val - prev_val) / prev_val
                if day_loss_pct < -settings.DAILY_LOSS_LIMIT_PCT:
                    logger.debug(
                        "Circuit breaker on %s (loss=%.2f%%) — no new orders today",
                        today, day_loss_pct * 100,
                    )
                    continue

        # ── Step 5: Generate signals for each symbol ──────────────────────────
        open_pos_count = sum(1 for p in positions.values() if p.is_open)

        for sym in symbols:
            df = price_dfs[sym]

            # Slice to data available strictly as of today (no lookahead)
            if hasattr(df.index, "date"):
                df_asof = df[df.index.date <= today]
            else:
                df_asof = df[df.index <= today]

            if len(df_asof) < 60:
                continue  # not enough warmup bars

            # -- Compute signal score ------------------------------------------
            if signal_override_fn is not None:
                signal_score = float(signal_override_fn(sym, today))
                features_snap: dict | None = None
            else:
                try:
                    from app.services.ml.predict import predict as ml_predict
                    result = ml_predict(sym, df_asof, today, model_version=model_version)
                    signal_score = result["signal_score"]
                    features_snap = result["features_snapshot"]
                except Exception as exc:
                    logger.debug("ML predict failed for %s on %s: %s", sym, today, exc)
                    continue

            # Persist MLSignal row
            sig_row = MLSignal(
                instrument_id=instruments[sym].id,
                as_of_date=today,
                model_version=model_version,
                signal_score=signal_score,
                features_used=features_snap,
            )
            db.add(sig_row)
            db.flush()

            # ── Step 6: LLM decision (optional) ──────────────────────────────
            decision_id: int | None = None
            action = "hold"
            pos_size_pct = 0.0

            if use_llm:
                try:
                    from app.services.llm_reasoning.decision_engine import get_or_create_decision
                    decision = get_or_create_decision(
                        db=db,
                        instrument_id=instruments[sym].id,
                        as_of_date=today,
                        ml_signal=sig_row,
                        price_df=df_asof,
                        portfolio_value=total_val,
                    )
                    action = decision.action
                    pos_size_pct = decision.position_size_pct or 0.0
                    decision_id = decision.id
                except Exception as exc:
                    logger.warning("LLM decision failed for %s on %s: %s", sym, today, exc)
                    # Fall through to ML-only rule below
                    use_llm_this_bar = False
                else:
                    use_llm_this_bar = True
            else:
                use_llm_this_bar = False

            if not use_llm_this_bar:
                # ML-only: simple threshold rule
                if signal_score > 0.3:
                    action = "buy"
                    # Scale position size proportionally to signal strength, capped at 1.0
                    pos_size_pct = min(signal_score / 3.0, 1.0)
                elif signal_score < -0.3:
                    action = "sell"
                    pos_size_pct = 0.0
                else:
                    action = "hold"

            # ── Step 7: Risk checks and order queuing ─────────────────────────
            if action == "buy":
                # Do not exceed max concurrent positions
                if open_pos_count >= settings.MAX_POSITIONS and not positions[sym].is_open:
                    logger.debug("MAX_POSITIONS reached — skipping buy for %s", sym)
                    continue
                # Size the order
                target_spend = total_val * settings.MAX_POSITION_PCT * pos_size_pct
                if target_spend < 1.0:
                    continue
                if cash < target_spend * 0.5:
                    continue  # not enough cash
                pending_orders.append({
                    "symbol": sym,
                    "side": "buy",
                    "target_spend": min(target_spend, cash * 0.99),
                    "decision_id": decision_id,
                })
                if not positions[sym].is_open:
                    open_pos_count += 1

            elif action == "sell" and positions[sym].is_open:
                pending_orders.append({
                    "symbol": sym,
                    "side": "sell",
                    "quantity": positions[sym].quantity,
                    "avg_entry_price": positions[sym].avg_entry_price,
                    "decision_id": decision_id,
                })

    # ── Bulk persist trades and snapshots ─────────────────────────────────────
    db.bulk_save_objects(db_trades)
    db.bulk_save_objects(db_snapshots)

    # ── Persist open Position rows (end-of-backtest state) ────────────────────
    for sym, pos in positions.items():
        if pos.is_open:
            p = db.query(Position).filter(
                Position.instrument_id == pos.instrument_id,
                Position.mode == "backtest",
                Position.backtest_run_id == run.id,
            ).first()
            if p is None:
                p = Position(
                    instrument_id=pos.instrument_id,
                    quantity=pos.quantity,
                    avg_entry_price=pos.avg_entry_price,
                    mode="backtest",
                    backtest_run_id=run.id,
                )
                db.add(p)
            else:
                p.quantity = pos.quantity
                p.avg_entry_price = pos.avg_entry_price

    # ── Compute metrics and finalise run ──────────────────────────────────────
    equity_s = pd.Series(
        [v for _, v in equity_series],
        index=pd.Index([d for d, _ in equity_series]),
    )
    # Only include sell-side trades in metrics (buy trades have pnl=None)
    closed_trades = [t for t in all_trades if t["pnl"] is not None]
    results = compute_all_metrics(equity_s, closed_trades)
    results["num_trades"] = len(all_trades)  # total orders (buy + sell)

    run.results = results
    run.finished_at = datetime.now(tz=timezone.utc)
    db.commit()

    logger.info(
        "Backtest %d done — CAGR=%.2f%% Sharpe=%.2f MaxDD=%.2f%% Trades=%d",
        run.id,
        results["cagr"] * 100,
        results["sharpe"],
        results["max_drawdown"] * 100,
        results["num_trades"],
    )
    return run
