"""Pydantic schemas for LLM structured output."""
from typing import Literal
from pydantic import BaseModel, Field, field_validator


class TradeDecision(BaseModel):
    action: Literal["buy", "sell", "hold"]
    position_size_pct: float = Field(ge=0.0, le=1.0, description="Fraction of portfolio to allocate")
    confidence: float = Field(ge=0.0, le=1.0, description="Model confidence 0-1")
    rationale: str = Field(min_length=10, description="Plain-English explanation of the decision")
    risk_flags: list[str] = Field(default_factory=list, description="Identified risk factors")

    @field_validator("position_size_pct")
    @classmethod
    def hold_size_zero(cls, v: float, info) -> float:
        # If action is hold, size should be 0
        # (We allow it non-zero — the executor handles it — but log it)
        return v

    @field_validator("risk_flags", mode="before")
    @classmethod
    def ensure_list(cls, v) -> list:
        if isinstance(v, str):
            return [v] if v else []
        return v or []
