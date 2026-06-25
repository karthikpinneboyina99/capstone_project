from datetime import datetime
from pydantic import BaseModel, ConfigDict


class TradeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str | None = None
    instrument_id: int
    side: str
    quantity: float
    price: float
    executed_at: datetime
    mode: str
    alpaca_order_id: str | None
