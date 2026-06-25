from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Instrument, MLSignal
from app.schemas import MLSignalOut

router = APIRouter()


@router.get("/today", response_model=list[MLSignalOut])
def get_today_signals(db: Session = Depends(get_db)) -> list[dict]:
    today = date.today()
    rows = (
        db.query(MLSignal, Instrument.symbol)
        .join(Instrument, MLSignal.instrument_id == Instrument.id)
        .filter(MLSignal.as_of_date == today)
        .all()
    )
    results = []
    for signal, symbol in rows:
        out = MLSignalOut.model_validate(signal)
        out.symbol = symbol
        results.append(out)
    return results


@router.get("/", response_model=list[MLSignalOut])
def list_signals(
    symbol: str | None = Query(None),
    start: date | None = Query(None),
    end: date | None = Query(None),
    db: Session = Depends(get_db),
) -> list[dict]:
    q = db.query(MLSignal, Instrument.symbol).join(
        Instrument, MLSignal.instrument_id == Instrument.id
    )
    if symbol:
        q = q.filter(Instrument.symbol == symbol.upper())
    if start:
        q = q.filter(MLSignal.as_of_date >= start)
    if end:
        q = q.filter(MLSignal.as_of_date <= end)
    rows = q.order_by(MLSignal.as_of_date.desc()).limit(500).all()
    results = []
    for signal, sym in rows:
        out = MLSignalOut.model_validate(signal)
        out.symbol = sym
        results.append(out)
    return results
