from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Instrument
from app.schemas import InstrumentOut

router = APIRouter()


@router.get("/", response_model=list[InstrumentOut])
def list_instruments(db: Session = Depends(get_db)) -> list[Instrument]:
    return db.query(Instrument).filter(Instrument.is_active == True).all()  # noqa: E712


@router.get("/{symbol}", response_model=InstrumentOut)
def get_instrument(symbol: str, db: Session = Depends(get_db)) -> Instrument:
    from fastapi import HTTPException
    inst = db.query(Instrument).filter(Instrument.symbol == symbol.upper()).first()
    if inst is None:
        raise HTTPException(status_code=404, detail=f"Instrument {symbol} not found")
    return inst
