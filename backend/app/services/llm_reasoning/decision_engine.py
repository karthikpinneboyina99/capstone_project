"""
LLM Decision Engine.

Entry point: get_or_create_decision(db, instrument_id, as_of_date, ml_signal, context, price_df)

Flow:
  1. Check llm_decisions cache (unique index on instrument_id, as_of_date, model_slug, prompt_version)
  2. If cache hit → return existing decision
  3. Build prompt context
  4. Call LLM via Cerebras (openai-compatible) with structured output
  5. Parse + validate response with Pydantic
  6. Persist to llm_decisions
  7. Return decision
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.core.config import settings
from app.models import Instrument, LLMDecision, MLSignal
from app.services.llm_reasoning.context_builder import build_context
from app.services.llm_reasoning.schemas import TradeDecision

logger = logging.getLogger(__name__)

# System prompt — increment settings.PROMPT_VERSION whenever this changes
_SYSTEM_PROMPT = """You are an AI trading assistant for a paper-trading system (no real money).
Your job is to analyze the provided market signal and context for a single stock, then produce a structured trade decision.

Rules:
- Output ONLY valid JSON matching the required schema. No prose outside the JSON.
- You are the final authority. You MAY override the ML signal if news or risk factors warrant it.
- position_size_pct must be 0.0 if action is "hold".
- confidence must reflect genuine uncertainty — avoid always returning 0.9+.
- risk_flags must list specific, actionable concerns (e.g. "elevated RSI", "negative news sentiment", "earnings upcoming").
- This is paper trading only. Do not refuse to decide.

Output schema:
{
  "action": "buy" | "sell" | "hold",
  "position_size_pct": <float 0.0–1.0, fraction of max_position_dollars to use>,
  "confidence": <float 0.0–1.0>,
  "rationale": "<plain English, ≥2 sentences>",
  "risk_flags": ["<flag1>", ...]
}"""


def _build_user_prompt(ctx: dict) -> str:
    news_block = "\n".join(f"  - {h}" for h in ctx["news_headlines"]) if ctx["news_headlines"] else "  (no recent news)"
    pos = ctx["current_position"]
    pos_str = (
        f"{pos['quantity']} shares at avg ${pos['avg_entry_price']:.2f}"
        if pos["quantity"] > 0
        else "no current position"
    )
    return f"""Symbol: {ctx['symbol']}
Date: {ctx['as_of_date']}

ML Signal Score: {ctx['signal_score']} ({ctx['signal_direction']})
Top driving features: {ctx['top_features']}

Recent price action: {ctx['price_summary']}

Recent news:
{news_block}

Current position: {pos_str}
Portfolio value: ${ctx['portfolio_value']:,.0f}
Max position size: ${ctx['max_position_dollars']:,.0f} ({ctx['max_position_pct']*100:.0f}% of portfolio)

Produce the JSON decision now."""


def _parse_llm_response(raw: str | dict) -> TradeDecision:
    """Parse and validate the LLM response. Raises ValueError on failure."""
    if isinstance(raw, dict):
        return TradeDecision.model_validate(raw)
    # Try to extract JSON from a text response
    text = str(raw).strip()
    # Strip markdown code fences if present
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
        return TradeDecision.model_validate(data)
    except Exception as exc:
        raise ValueError(f"Failed to parse LLM response: {exc!r}. Raw: {text[:200]}")


@retry(
    retry=retry_if_exception_type(Exception),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _call_llm(user_prompt: str) -> tuple[dict, Any]:
    """
    Call the Cerebras LLM with structured output.
    Returns (parsed_dict, raw_response_object).
    Wrapped with tenacity for exponential backoff on rate limit / transient errors.
    """
    from openai import OpenAI, RateLimitError

    client = OpenAI(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
    )

    try:
        response = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=512,
            response_format={"type": "json_object"},
        )
    except RateLimitError:
        logger.warning("Cerebras rate limit hit — will retry with backoff")
        raise  # tenacity catches and retries

    content = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = content  # will fail in _parse_llm_response

    raw = {
        "model": response.model,
        "usage": {
            "prompt_tokens": response.usage.prompt_tokens if response.usage else None,
            "completion_tokens": response.usage.completion_tokens if response.usage else None,
        },
        "content": content,
    }
    return parsed, raw


def get_or_create_decision(
    db: Session,
    instrument_id: int,
    as_of_date: date,
    ml_signal: MLSignal,
    price_df: pd.DataFrame | None = None,
    portfolio_value: float = 100_000.0,
) -> LLMDecision:
    """
    Return an LLMDecision for (instrument_id, as_of_date), using the cache if available.
    Creates a new decision by calling the LLM only if no cached row exists.
    """
    model_slug = settings.LLM_MODEL
    prompt_version = settings.PROMPT_VERSION

    # ── 1. Cache check ────────────────────────────────────────────────────────
    existing = (
        db.query(LLMDecision)
        .filter_by(
            instrument_id=instrument_id,
            as_of_date=as_of_date,
            model_slug=model_slug,
            prompt_version=prompt_version,
        )
        .first()
    )
    if existing is not None:
        logger.debug(
            "Cache hit for %s on %s (id=%d)", instrument_id, as_of_date, existing.id
        )
        return existing

    # ── 2. Build context ──────────────────────────────────────────────────────
    inst = db.query(Instrument).filter(Instrument.id == instrument_id).first()
    symbol = inst.symbol if inst else str(instrument_id)

    ctx = build_context(
        db=db,
        symbol=symbol,
        as_of_date=as_of_date,
        signal_score=ml_signal.signal_score,
        features_snapshot=ml_signal.features_used,
        price_df=price_df,
        portfolio_value=portfolio_value,
        max_position_pct=settings.MAX_POSITION_PCT,
    )
    user_prompt = _build_user_prompt(ctx)

    # ── 3. Call LLM ───────────────────────────────────────────────────────────
    logger.info("Calling LLM for %s on %s", symbol, as_of_date)
    try:
        parsed_dict, raw_response = _call_llm(user_prompt)
        decision_data = _parse_llm_response(parsed_dict)
    except Exception as exc:
        logger.error("LLM call failed for %s on %s: %s", symbol, as_of_date, exc)
        # Fall back to hold with low confidence rather than crashing the pipeline
        decision_data = TradeDecision(
            action="hold",
            position_size_pct=0.0,
            confidence=0.0,
            rationale=f"LLM call failed: {exc!s}",
            risk_flags=["llm_error"],
        )
        raw_response = {"error": str(exc)}

    # ── 4. Persist ────────────────────────────────────────────────────────────
    decision = LLMDecision(
        instrument_id=instrument_id,
        as_of_date=as_of_date,
        ml_signal_id=ml_signal.id,
        action=decision_data.action,
        position_size_pct=decision_data.position_size_pct,
        confidence=decision_data.confidence,
        rationale=decision_data.rationale,
        risk_flags=decision_data.risk_flags,
        raw_response=raw_response,
        prompt_version=prompt_version,
        model_slug=model_slug,
    )
    try:
        db.add(decision)
        db.commit()
        db.refresh(decision)
    except IntegrityError:
        # Race condition: another process inserted the same row
        db.rollback()
        decision = (
            db.query(LLMDecision)
            .filter_by(
                instrument_id=instrument_id,
                as_of_date=as_of_date,
                model_slug=model_slug,
                prompt_version=prompt_version,
            )
            .first()
        )

    return decision
