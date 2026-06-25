from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import BacktestRun
from app.schemas import BacktestRunOut, BacktestTriggerIn

router = APIRouter()


@router.get("/", response_model=list[BacktestRunOut])
def list_backtests(db: Session = Depends(get_db)) -> list[BacktestRun]:
    return (
        db.query(BacktestRun)
        .order_by(BacktestRun.started_at.desc())
        .limit(50)
        .all()
    )


@router.get("/{run_id}", response_model=BacktestRunOut)
def get_backtest(run_id: int, db: Session = Depends(get_db)) -> BacktestRun:
    run = db.query(BacktestRun).filter(BacktestRun.id == run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    return run


@router.post("/trigger", response_model=BacktestRunOut, status_code=202)
def trigger_backtest(payload: BacktestTriggerIn, db: Session = Depends(get_db)) -> BacktestRun:
    """
    Creates a BacktestRun record. The actual computation is run by the
    backtesting service (called directly or via a background task).
    This endpoint is intentionally thin — it just registers the intent.
    """
    from datetime import datetime, timezone

    run = BacktestRun(
        started_at=datetime.now(tz=timezone.utc),
        date_range_start=payload.date_range_start,
        date_range_end=payload.date_range_end,
        strategy_version=payload.strategy_version,
        params=payload.params,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run
