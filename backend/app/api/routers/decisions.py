from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Instrument, LLMDecision, MLSignal
from app.schemas import DecisionOut

router = APIRouter()


def _enrich(decision: LLMDecision, symbol: str, signal_score: float | None) -> DecisionOut:
    out = DecisionOut.model_validate(decision)
    out.symbol = symbol
    out.signal_score = signal_score
    return out


@router.get("/today", response_model=list[DecisionOut])
def get_today_decisions(db: Session = Depends(get_db)) -> list[DecisionOut]:
    today = date.today()
    rows = (
        db.query(LLMDecision, Instrument.symbol, MLSignal.signal_score)
        .join(Instrument, LLMDecision.instrument_id == Instrument.id)
        .outerjoin(MLSignal, LLMDecision.ml_signal_id == MLSignal.id)
        .filter(LLMDecision.as_of_date == today)
        .all()
    )
    return [_enrich(d, sym, score) for d, sym, score in rows]


@router.get("/{decision_id}", response_model=DecisionOut)
def get_decision(decision_id: int, db: Session = Depends(get_db)) -> DecisionOut:
    from fastapi import HTTPException
    row = (
        db.query(LLMDecision, Instrument.symbol, MLSignal.signal_score)
        .join(Instrument, LLMDecision.instrument_id == Instrument.id)
        .outerjoin(MLSignal, LLMDecision.ml_signal_id == MLSignal.id)
        .filter(LLMDecision.id == decision_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    d, sym, score = row
    return _enrich(d, sym, score)
