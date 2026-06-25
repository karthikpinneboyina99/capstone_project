"""
Unit tests for the LLM reasoning layer.
The OpenAI client is always mocked — no real API calls.
"""
import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))

from app.services.llm_reasoning.schemas import TradeDecision
from app.services.llm_reasoning.decision_engine import _parse_llm_response, _build_user_prompt
from app.services.llm_reasoning.context_builder import build_context


# ── TradeDecision schema validation ──────────────────────────────────────────

class TestTradeDecision:
    def test_valid_buy(self):
        d = TradeDecision(action="buy", position_size_pct=0.5, confidence=0.8, rationale="Strong uptrend with bullish momentum.")
        assert d.action == "buy"
        assert d.risk_flags == []

    def test_valid_hold_with_flags(self):
        d = TradeDecision(action="hold", position_size_pct=0.0, confidence=0.6, rationale="Waiting for clearer signal.", risk_flags=["elevated RSI"])
        assert d.risk_flags == ["elevated RSI"]

    def test_rejects_position_size_over_1(self):
        with pytest.raises(Exception):
            TradeDecision(action="buy", position_size_pct=1.5, confidence=0.5, rationale="too big")

    def test_rejects_confidence_negative(self):
        with pytest.raises(Exception):
            TradeDecision(action="buy", position_size_pct=0.5, confidence=-0.1, rationale="bad confidence")

    def test_invalid_action(self):
        with pytest.raises(Exception):
            TradeDecision(action="short", position_size_pct=0.3, confidence=0.7, rationale="not allowed")

    def test_risk_flags_string_coerced_to_list(self):
        d = TradeDecision(action="hold", position_size_pct=0.0, confidence=0.5, rationale="testing coerce", risk_flags="single_flag")
        assert d.risk_flags == ["single_flag"]


# ── _parse_llm_response ───────────────────────────────────────────────────────

class TestParseLLMResponse:
    def _valid_payload(self):
        return {
            "action": "buy",
            "position_size_pct": 0.8,
            "confidence": 0.75,
            "rationale": "Technical momentum is strong with RSI not yet overbought.",
            "risk_flags": ["sector rotation risk"],
        }

    def test_parses_dict(self):
        result = _parse_llm_response(self._valid_payload())
        assert isinstance(result, TradeDecision)
        assert result.action == "buy"

    def test_parses_json_string(self):
        result = _parse_llm_response(json.dumps(self._valid_payload()))
        assert result.action == "buy"

    def test_parses_json_with_markdown_fence(self):
        fenced = "```json\n" + json.dumps(self._valid_payload()) + "\n```"
        result = _parse_llm_response(fenced)
        assert result.action == "buy"

    def test_raises_on_malformed_json(self):
        with pytest.raises(ValueError):
            _parse_llm_response("not json at all {{{")

    def test_raises_on_missing_required_field(self):
        bad = {"action": "buy", "confidence": 0.7}  # missing position_size_pct, rationale
        with pytest.raises(Exception):
            _parse_llm_response(bad)

    def test_hold_action_accepted(self):
        payload = {**self._valid_payload(), "action": "hold", "position_size_pct": 0.0}
        result = _parse_llm_response(payload)
        assert result.action == "hold"


# ── get_or_create_decision: cache hit ────────────────────────────────────────

class TestGetOrCreateDecision:
    def _make_db_with_existing_decision(self):
        from app.models import LLMDecision
        existing = LLMDecision(
            id=42,
            instrument_id=1,
            as_of_date=date(2024, 6, 1),
            action="buy",
            position_size_pct=0.5,
            confidence=0.8,
            rationale="Cached decision.",
            risk_flags=[],
            prompt_version=1,
            model_slug="gpt-oss-120b",
        )
        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = existing
        return db, existing

    def test_cache_hit_skips_llm(self):
        from app.services.llm_reasoning.decision_engine import get_or_create_decision

        db, existing = self._make_db_with_existing_decision()
        signal = MagicMock()
        signal.signal_score = 0.5
        signal.features_used = {}
        signal.id = 99

        with patch("app.services.llm_reasoning.decision_engine._call_llm") as mock_llm:
            result = get_or_create_decision(db, 1, date(2024, 6, 1), signal)

        mock_llm.assert_not_called()
        assert result.id == 42

    def test_cache_miss_calls_llm(self):
        from app.services.llm_reasoning.decision_engine import get_or_create_decision

        db = MagicMock()
        # First query (cache check) returns None; second query (instrument) returns mock
        inst_mock = MagicMock()
        inst_mock.symbol = "AAPL"
        inst_mock.id = 1
        inst_mock.quantity = 0  # Position queries return this mock; quantity=0 avoids MagicMock comparison

        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            m = MagicMock()
            if call_count[0] == 1:
                m.filter_by.return_value.first.return_value = None  # cache miss
            else:
                m.filter.return_value.first.return_value = inst_mock
                m.filter_by.return_value.first.return_value = None
            return m

        db.query.side_effect = side_effect
        db.add = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()

        signal = MagicMock()
        signal.signal_score = 0.3
        signal.features_used = {"rsi14": 55.0}
        signal.id = 5

        fake_parsed = {
            "action": "hold",
            "position_size_pct": 0.0,
            "confidence": 0.6,
            "rationale": "Signal is neutral; holding position and waiting for confirmation.",
            "risk_flags": [],
        }
        fake_raw = {"model": "gpt-oss-120b", "content": json.dumps(fake_parsed)}

        with patch("app.services.llm_reasoning.decision_engine._call_llm", return_value=(fake_parsed, fake_raw)):
            result = get_or_create_decision(db, 1, date(2024, 6, 1), signal)

        db.add.assert_called_once()
        db.commit.assert_called_once()
