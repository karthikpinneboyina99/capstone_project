from datetime import date
from pydantic import BaseModel, ConfigDict


class MLSignalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    instrument_id: int
    symbol: str | None = None  # populated from join
    as_of_date: date
    model_version: str
    signal_score: float
