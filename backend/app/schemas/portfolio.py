from datetime import date
from pydantic import BaseModel, ConfigDict


class PositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str | None = None
    instrument_id: int
    quantity: float
    avg_entry_price: float
    current_price: float | None = None
    unrealized_pnl: float | None = None
    mode: str


class PortfolioSummaryOut(BaseModel):
    cash: float
    equity: float
    total_value: float
    as_of_date: date
    day_pnl: float | None = None
    mode: str = "paper"
