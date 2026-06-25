from datetime import date
from pydantic import BaseModel, ConfigDict


class DecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str | None = None  # populated from join
    instrument_id: int
    as_of_date: date
    action: str
    position_size_pct: float | None
    confidence: float | None
    rationale: str | None
    risk_flags: list[str]
    prompt_version: int
    model_slug: str
    signal_score: float | None = None  # from joined ml_signal
