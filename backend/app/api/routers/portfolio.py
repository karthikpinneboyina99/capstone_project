from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Instrument, Position, PortfolioSnapshot
from app.schemas import PortfolioSummaryOut, PositionOut

router = APIRouter()


@router.get("/summary", response_model=PortfolioSummaryOut)
def get_portfolio_summary(db: Session = Depends(get_db)) -> PortfolioSummaryOut:
    snap = (
        db.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.mode == "paper")
        .order_by(PortfolioSnapshot.as_of_date.desc())
        .first()
    )
    if snap is None:
        return PortfolioSummaryOut(
            cash=100_000.0,
            equity=0.0,
            total_value=100_000.0,
            as_of_date=date.today(),
            mode="paper",
        )
    return PortfolioSummaryOut(
        cash=snap.cash,
        equity=snap.equity,
        total_value=snap.total_value,
        as_of_date=snap.as_of_date,
        mode=snap.mode,
    )


@router.get("/positions", response_model=list[PositionOut])
def list_positions(db: Session = Depends(get_db)) -> list[PositionOut]:
    rows = (
        db.query(Position, Instrument.symbol)
        .join(Instrument, Position.instrument_id == Instrument.id)
        .filter(Position.mode == "paper", Position.backtest_run_id == None)  # noqa: E711
        .filter(Position.quantity > 0)
        .all()
    )
    results = []
    for pos, sym in rows:
        out = PositionOut.model_validate(pos)
        out.symbol = sym
        results.append(out)
    return results
