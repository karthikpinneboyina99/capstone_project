from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Instrument, Trade
from app.schemas import TradeOut

router = APIRouter()


@router.get("/", response_model=list[TradeOut])
def list_trades(
    symbol: str | None = Query(None),
    mode: str | None = Query(None),
    start: date | None = Query(None),
    end: date | None = Query(None),
    limit: int = Query(200, le=1000),
    db: Session = Depends(get_db),
) -> list[TradeOut]:
    q = db.query(Trade, Instrument.symbol).join(
        Instrument, Trade.instrument_id == Instrument.id
    )
    if symbol:
        q = q.filter(Instrument.symbol == symbol.upper())
    if mode:
        q = q.filter(Trade.mode == mode)
    if start:
        q = q.filter(Trade.executed_at >= start)
    if end:
        q = q.filter(Trade.executed_at <= end)
    rows = q.order_by(Trade.executed_at.desc()).limit(limit).all()
    results = []
    for trade, sym in rows:
        out = TradeOut.model_validate(trade)
        out.symbol = sym
        results.append(out)
    return results
