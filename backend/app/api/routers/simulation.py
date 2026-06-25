"""
Simulation trading endpoints.
All records use mode="simulation" — completely separate from the live paper executor.

Endpoints:
  GET  /simulation/account          — cash, equity, total_value, return_pct, trade_count
  GET  /simulation/positions        — list of open positions with current P&L
  GET  /simulation/trades           — trade history
  POST /simulation/buy              — {symbol, quantity, price?}  price optional (uses live sim price)
  POST /simulation/sell             — {symbol, quantity, price?}
  POST /simulation/close/{symbol}   — close entire position
  POST /simulation/reset            — reset to $100k cash, clear all simulation positions/trades
  POST /simulation/ai/suggest       — ask AI to suggest next trades given current portfolio
  POST /simulation/ai/build         — AI autonomously builds a profitable portfolio allocation
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models import Instrument, Position, PortfolioSnapshot, Trade
from app.services.simulation.state import get_all_prices, get_price

logger = logging.getLogger(__name__)
router = APIRouter()

STARTING_CASH = 100_000.0
MODE = "simulation"


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class TradeRequest(BaseModel):
    symbol: str
    quantity: float
    price: float | None = None


class AccountOut(BaseModel):
    cash: float
    equity: float
    total_value: float
    return_pct: float
    pnl: float
    trade_count: int


class PositionSimOut(BaseModel):
    symbol: str
    quantity: float
    avg_entry_price: float
    current_price: float | None
    current_value: float | None
    pnl: float | None
    pnl_pct: float | None


class TradeSimOut(BaseModel):
    id: int
    symbol: str
    side: str
    quantity: float
    price: float
    executed_at: datetime
    mode: str


class ResetOut(BaseModel):
    status: str
    cash: float


class TradeSuggestion(BaseModel):
    symbol: str
    action: str
    quantity: float
    reason: str


class SuggestOut(BaseModel):
    suggestions: list[TradeSuggestion]


class BuildOut(BaseModel):
    trades_executed: list[dict[str, Any]]
    portfolio_after: dict[str, Any]
    message: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_or_create_instrument(db: Session, symbol: str) -> Instrument:
    inst = db.query(Instrument).filter(Instrument.symbol == symbol.upper()).first()
    if inst is None:
        inst = Instrument(symbol=symbol.upper(), is_active=True)
        db.add(inst)
        db.flush()
    return inst


def _compute_cash(db: Session) -> float:
    """Cash = STARTING_CASH - sum(buy fills) + sum(sell fills) for simulation trades."""
    rows = (
        db.query(Trade.side, func.sum(Trade.quantity * Trade.price))
        .filter(Trade.mode == MODE)
        .group_by(Trade.side)
        .all()
    )
    buy_spent = 0.0
    sell_received = 0.0
    for side, total in rows:
        if total is None:
            continue
        if side == "buy":
            buy_spent = float(total)
        elif side == "sell":
            sell_received = float(total)
    return STARTING_CASH - buy_spent + sell_received


def _compute_equity(db: Session, prices: dict[str, float]) -> float:
    """Equity = sum of position market values."""
    rows = (
        db.query(Position, Instrument.symbol)
        .join(Instrument, Position.instrument_id == Instrument.id)
        .filter(Position.mode == MODE, Position.backtest_run_id == None)  # noqa: E711
        .filter(Position.quantity > 0)
        .all()
    )
    equity = 0.0
    for pos, sym in rows:
        px = prices.get(sym)
        if px is None:
            # Fall back to avg entry price if no live price
            px = pos.avg_entry_price
        equity += pos.quantity * px
    return equity


def _get_price_for_symbol(symbol: str) -> float | None:
    """Get current price: first try shared state, then yfinance."""
    px = get_price(symbol)
    if px is not None:
        return px
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        logger.warning("yfinance fallback failed for %s", symbol)
    return None


def _execute_trade(
    db: Session,
    symbol: str,
    side: str,
    quantity: float,
    price: float | None,
) -> dict[str, Any]:
    """Core buy/sell logic. Returns a dict with trade and position info."""
    symbol = symbol.upper()
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be positive")

    # Resolve price
    if price is None:
        price = _get_price_for_symbol(symbol)
    if price is None:
        raise HTTPException(
            status_code=400,
            detail=f"No price available for {symbol}. Start the /stream/prices feed or provide price.",
        )

    inst = _get_or_create_instrument(db, symbol)

    # Validate sell: must have sufficient position
    if side == "sell":
        pos = (
            db.query(Position)
            .filter(
                Position.instrument_id == inst.id,
                Position.mode == MODE,
                Position.backtest_run_id == None,  # noqa: E711
            )
            .first()
        )
        if pos is None or pos.quantity < quantity:
            held = pos.quantity if pos else 0.0
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient position: have {held}, trying to sell {quantity}",
            )

    # Validate buy: must have sufficient cash
    if side == "buy":
        cash = _compute_cash(db)
        cost = price * quantity
        if cost > cash:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient cash: need {cost:.2f}, have {cash:.2f}",
            )

    # Create Trade
    trade = Trade(
        instrument_id=inst.id,
        decision_id=None,
        side=side,
        quantity=quantity,
        price=price,
        executed_at=datetime.now(tz=timezone.utc),
        mode=MODE,
        backtest_run_id=None,
    )
    db.add(trade)
    db.flush()

    # Update or create Position
    pos = (
        db.query(Position)
        .filter(
            Position.instrument_id == inst.id,
            Position.mode == MODE,
            Position.backtest_run_id == None,  # noqa: E711
        )
        .first()
    )
    if side == "buy":
        if pos is None:
            pos = Position(
                instrument_id=inst.id,
                quantity=quantity,
                avg_entry_price=price,
                mode=MODE,
                backtest_run_id=None,
            )
            db.add(pos)
        else:
            total_cost = pos.quantity * pos.avg_entry_price + quantity * price
            pos.quantity += quantity
            pos.avg_entry_price = total_cost / pos.quantity
    else:  # sell
        pos.quantity -= quantity
        # avg_entry_price unchanged on sells

    db.commit()

    return {
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "price": price,
        "position_quantity": pos.quantity,
        "avg_entry_price": pos.avg_entry_price,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/account", response_model=AccountOut)
def get_account(db: Session = Depends(get_db)) -> AccountOut:
    prices = get_all_prices()
    cash = _compute_cash(db)
    equity = _compute_equity(db, prices)
    total_value = cash + equity
    pnl = total_value - STARTING_CASH
    return_pct = (pnl / STARTING_CASH) * 100.0
    trade_count = db.query(func.count(Trade.id)).filter(Trade.mode == MODE).scalar() or 0
    return AccountOut(
        cash=cash,
        equity=equity,
        total_value=total_value,
        return_pct=return_pct,
        pnl=pnl,
        trade_count=trade_count,
    )


@router.get("/positions", response_model=list[PositionSimOut])
def list_positions(db: Session = Depends(get_db)) -> list[PositionSimOut]:
    rows = (
        db.query(Position, Instrument.symbol)
        .join(Instrument, Position.instrument_id == Instrument.id)
        .filter(Position.mode == MODE, Position.backtest_run_id == None)  # noqa: E711
        .filter(Position.quantity > 0)
        .all()
    )
    prices = get_all_prices()
    result = []
    for pos, sym in rows:
        px = prices.get(sym)
        if px is not None:
            current_value = pos.quantity * px
            pnl = (px - pos.avg_entry_price) * pos.quantity
            cost_basis = pos.avg_entry_price * pos.quantity
            pnl_pct = (pnl / cost_basis) * 100.0 if cost_basis else None
        else:
            current_value = None
            pnl = None
            pnl_pct = None
        result.append(
            PositionSimOut(
                symbol=sym,
                quantity=pos.quantity,
                avg_entry_price=pos.avg_entry_price,
                current_price=px,
                current_value=current_value,
                pnl=pnl,
                pnl_pct=pnl_pct,
            )
        )
    return result


@router.get("/trades", response_model=list[TradeSimOut])
def list_trades(db: Session = Depends(get_db)) -> list[TradeSimOut]:
    rows = (
        db.query(Trade, Instrument.symbol)
        .join(Instrument, Trade.instrument_id == Instrument.id)
        .filter(Trade.mode == MODE)
        .order_by(Trade.executed_at.desc())
        .limit(500)
        .all()
    )
    return [
        TradeSimOut(
            id=trade.id,
            symbol=sym,
            side=trade.side,
            quantity=trade.quantity,
            price=trade.price,
            executed_at=trade.executed_at,
            mode=trade.mode,
        )
        for trade, sym in rows
    ]


@router.post("/buy")
def buy(req: TradeRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _execute_trade(db, req.symbol, "buy", req.quantity, req.price)


@router.post("/sell")
def sell(req: TradeRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _execute_trade(db, req.symbol, "sell", req.quantity, req.price)


@router.post("/close/{symbol}")
def close_position(symbol: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    symbol = symbol.upper()
    inst = db.query(Instrument).filter(Instrument.symbol == symbol).first()
    if inst is None:
        raise HTTPException(status_code=404, detail=f"No position found for {symbol}")
    pos = (
        db.query(Position)
        .filter(
            Position.instrument_id == inst.id,
            Position.mode == MODE,
            Position.backtest_run_id == None,  # noqa: E711
        )
        .first()
    )
    if pos is None or pos.quantity <= 0:
        raise HTTPException(status_code=404, detail=f"No open position for {symbol}")
    return _execute_trade(db, symbol, "sell", pos.quantity, None)


@router.post("/reset", response_model=ResetOut)
def reset_simulation(db: Session = Depends(get_db)) -> ResetOut:
    db.query(Trade).filter(Trade.mode == MODE).delete(synchronize_session=False)
    db.query(Position).filter(Position.mode == MODE).delete(synchronize_session=False)
    db.query(PortfolioSnapshot).filter(PortfolioSnapshot.mode == MODE).delete(
        synchronize_session=False
    )
    db.commit()
    return ResetOut(status="reset", cash=STARTING_CASH)


@router.post("/ai/suggest", response_model=SuggestOut)
def ai_suggest(db: Session = Depends(get_db)) -> SuggestOut:
    from openai import OpenAI

    prices = get_all_prices()
    rows = (
        db.query(Position, Instrument.symbol)
        .join(Instrument, Position.instrument_id == Instrument.id)
        .filter(Position.mode == MODE, Position.backtest_run_id == None)  # noqa: E711
        .filter(Position.quantity > 0)
        .all()
    )
    positions_desc = []
    for pos, sym in rows:
        px = prices.get(sym, pos.avg_entry_price)
        pnl = (px - pos.avg_entry_price) * pos.quantity
        positions_desc.append(
            f"{sym}: qty={pos.quantity}, avg_entry={pos.avg_entry_price:.2f}, "
            f"current={px:.2f}, pnl={pnl:.2f}"
        )

    cash = _compute_cash(db)
    prices_desc = ", ".join(
        f"{sym}=${px:.2f}" for sym, px in sorted(prices.items()) if sym in settings.WATCHLIST
    )

    prompt = f"""You are a paper-trading assistant analyzing a simulation portfolio.

Current cash: ${cash:,.2f}
Current positions:
{chr(10).join(positions_desc) if positions_desc else "None"}

Current prices: {prices_desc if prices_desc else "Not available"}
Watchlist: {", ".join(settings.WATCHLIST)}

Suggest 3-5 trades to improve the portfolio. Consider diversification, momentum, and risk.

Return ONLY valid JSON (no markdown, no explanation outside JSON):
{{
  "suggestions": [
    {{"symbol": "AAPL", "action": "buy", "quantity": 5, "reason": "strong momentum"}},
    ...
  ]
}}"""

    try:
        from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
        from openai import RateLimitError as _RLE

        @retry(retry=retry_if_exception_type(_RLE), wait=wait_exponential(min=4, max=30), stop=stop_after_attempt(3), reraise=True)
        def _call():
            client = OpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL)
            return client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=512,
                temperature=0.3,
                response_format={"type": "json_object"},
            )

        response = _call()
        raw = (response.choices[0].message.content or "").strip()
        data = json.loads(raw)
        suggestions = [TradeSuggestion(**s) for s in data.get("suggestions", [])]
    except Exception as exc:
        err = str(exc)
        if "429" in err or "rate" in err.lower() or "queue" in err.lower():
            raise HTTPException(status_code=429, detail="Cerebras is busy right now (free tier rate limit). Please wait 30 seconds and try again.")
        logger.warning("AI suggest failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}")

    return SuggestOut(suggestions=suggestions)


@router.post("/ai/build", response_model=BuildOut)
def ai_build(db: Session = Depends(get_db)) -> BuildOut:
    from openai import OpenAI

    prices = get_all_prices()
    # Fall back to yfinance if stream not running
    if not prices:
        for sym in settings.WATCHLIST:
            px = _get_price_for_symbol(sym)
            if px:
                prices[sym] = px

    rows = (
        db.query(Position, Instrument.symbol)
        .join(Instrument, Position.instrument_id == Instrument.id)
        .filter(Position.mode == MODE, Position.backtest_run_id == None)  # noqa: E711
        .filter(Position.quantity > 0)
        .all()
    )
    positions_desc = []
    for pos, sym in rows:
        px = prices.get(sym, pos.avg_entry_price)
        positions_desc.append(
            f"{sym}: qty={pos.quantity}, avg_entry={pos.avg_entry_price:.2f}, current={px:.2f}"
        )

    cash = _compute_cash(db)
    equity = _compute_equity(db, prices)
    total_value = cash + equity
    prices_desc = "\n".join(
        f"  {sym}: ${prices[sym]:.2f}"
        for sym in settings.WATCHLIST
        if sym in prices
    )

    prompt = f"""You are managing a paper trading portfolio of ${total_value:,.2f}.
Current cash: ${cash:,.2f}
Current equity: ${equity:,.2f}
Current positions:
{chr(10).join(positions_desc) if positions_desc else "  None"}

Current prices:
{prices_desc if prices_desc else "  (prices unavailable — use reasonable estimates)"}

Watchlist: {", ".join(settings.WATCHLIST)}

Build an optimally diversified portfolio. Allocate the available cash across 4-7 symbols.
Max position: 20% of total portfolio per symbol.
Prefer a mix of growth (NVDA, META, AAPL) and stability (SPY, QQQ, JPM).
Only suggest BUY trades using available cash. Do not suggest sells unless reducing overweight positions.

Return ONLY valid JSON (no markdown, no extra text):
{{
  "trades": [
    {{"symbol": "AAPL", "action": "buy", "quantity": 5, "reason": "strong momentum"}},
    ...
  ],
  "rationale": "Overall portfolio strategy explanation"
}}"""

    try:
        from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
        from openai import RateLimitError as _RLE

        @retry(retry=retry_if_exception_type(_RLE), wait=wait_exponential(min=4, max=30), stop=stop_after_attempt(3), reraise=True)
        def _call():
            client = OpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL)
            return client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                temperature=0.2,
                response_format={"type": "json_object"},
            )

        response = _call()
        raw = (response.choices[0].message.content or "").strip()
        data = json.loads(raw)
    except Exception as exc:
        err = str(exc)
        if "429" in err or "rate" in err.lower() or "queue" in err.lower():
            raise HTTPException(status_code=429, detail="Cerebras is busy right now (free tier rate limit). Please wait 30 seconds and try again.")
        logger.warning("AI build failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}")

    rationale = data.get("rationale", "")
    trades_executed = []
    errors = []
    for t in data.get("trades", []):
        sym = t.get("symbol", "").upper()
        action = t.get("action", "buy").lower()
        quantity = float(t.get("quantity", 0))
        reason = t.get("reason", "")
        if quantity <= 0 or sym not in settings.WATCHLIST:
            continue
        price = prices.get(sym)
        try:
            result = _execute_trade(db, sym, action, quantity, price)
            result["reason"] = reason
            trades_executed.append(result)
        except HTTPException as exc:
            errors.append({"symbol": sym, "error": exc.detail})
        except Exception as exc:
            errors.append({"symbol": sym, "error": str(exc)})

    # Refresh account after trades
    prices_after = get_all_prices() or prices
    cash_after = _compute_cash(db)
    equity_after = _compute_equity(db, prices_after)
    portfolio_after = {
        "cash": cash_after,
        "equity": equity_after,
        "total_value": cash_after + equity_after,
        "errors": errors,
    }

    message = rationale or f"Executed {len(trades_executed)} trades."
    if errors:
        message += f" {len(errors)} trade(s) failed (see portfolio_after.errors)."

    return BuildOut(
        trades_executed=trades_executed,
        portfolio_after=portfolio_after,
        message=message,
    )
