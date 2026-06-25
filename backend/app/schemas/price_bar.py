from datetime import datetime
from pydantic import BaseModel, ConfigDict


class PriceBarOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    instrument_id: int
    timestamp: datetime
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int | None
    timeframe: str
