from datetime import date, datetime
from pydantic import BaseModel, ConfigDict


class BacktestRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date_range_start: date | None
    date_range_end: date | None
    strategy_version: str | None
    results: dict | None
    started_at: datetime | None
    finished_at: datetime | None


class BacktestTriggerIn(BaseModel):
    date_range_start: date
    date_range_end: date
    strategy_version: str = "v1"
    params: dict = {}
