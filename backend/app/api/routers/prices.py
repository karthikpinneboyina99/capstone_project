from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Instrument, PriceBar
from app.schemas import PriceBarOut

router = APIRouter()


@router.get("/{symbol}", response_model=list[PriceBarOut])
def get_prices(
    symbol: str,
    start: date | None = Query(None),
    end: date | None = Query(None),
    limit: int = Query(252, le=2000),
    db: Session = Depends(get_db),
) -> list[PriceBar]:
    from fastapi import HTTPException

    inst = db.query(Instrument).filter(Instrument.symbol == symbol.upper()).first()
    if inst is None:
        raise HTTPException(status_code=404, detail=f"Instrument {symbol} not found")

    q = db.query(PriceBar).filter(PriceBar.instrument_id == inst.id)
    if start:
        q = q.filter(PriceBar.timestamp >= start)
    if end:
        q = q.filter(PriceBar.timestamp <= end)
    return q.order_by(PriceBar.timestamp.desc()).limit(limit).all()
