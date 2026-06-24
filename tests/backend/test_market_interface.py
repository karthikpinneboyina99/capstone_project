"""
Unit tests for the unified market data interface:
  - Bar and Quote dataclasses
  - create_provider() factory
"""
import os
import dataclasses
from datetime import date

import pandas as pd
import pytest

from app.services.data_ingestion.market_interface import Bar, Quote, create_provider


# ---------------------------------------------------------------------------
# Bar dataclass
# ---------------------------------------------------------------------------

class TestBar:
    def test_fields_exist(self):
        b = Bar(
            ticker="AAPL",
            date=date(2023, 1, 3),
            open=150.0,
            high=155.0,
            low=149.0,
            close=153.5,
            volume=82_000_000,
            vwap=152.7,
        )
        assert b.ticker == "AAPL"
        assert b.date == date(2023, 1, 3)
        assert b.open == 150.0
        assert b.high == 155.0
        assert b.low == 149.0
        assert b.close == 153.5
        assert b.volume == 82_000_000
        assert b.vwap == 152.7

    def test_vwap_can_be_none(self):
        b = Bar(
            ticker="SPY",
            date=date(2023, 1, 3),
            open=400.0, high=402.0, low=398.0, close=401.0,
            volume=100_000, vwap=None,
        )
        assert b.vwap is None

    def test_frozen(self):
        b = Bar(
            ticker="AAPL",
            date=date(2023, 1, 3),
            open=150.0, high=155.0, low=149.0, close=153.5,
            volume=82_000_000, vwap=152.7,
        )
        with pytest.raises((dataclasses.FrozenInstanceError, TypeError, AttributeError)):
            b.close = 999.0  # type: ignore[misc]

    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(Bar)

    def test_equality(self):
        b1 = Bar("AAPL", date(2023, 1, 3), 150.0, 155.0, 149.0, 153.5, 82_000_000, 152.7)
        b2 = Bar("AAPL", date(2023, 1, 3), 150.0, 155.0, 149.0, 153.5, 82_000_000, 152.7)
        assert b1 == b2

    def test_hashable(self):
        b = Bar("AAPL", date(2023, 1, 3), 150.0, 155.0, 149.0, 153.5, 82_000_000, 152.7)
        s = {b}
        assert b in s


# ---------------------------------------------------------------------------
# Quote dataclass
# ---------------------------------------------------------------------------

class TestQuote:
    def test_fields_exist(self):
        ts = pd.Timestamp("2023-01-03 15:30:00", tz="UTC")
        q = Quote(
            ticker="MSFT",
            bid=370.0,
            ask=370.05,
            bid_size=200,
            ask_size=150,
            timestamp=ts,
        )
        assert q.ticker == "MSFT"
        assert q.bid == 370.0
        assert q.ask == 370.05
        assert q.bid_size == 200
        assert q.ask_size == 150
        assert q.timestamp == ts

    def test_frozen(self):
        ts = pd.Timestamp("2023-01-03 15:30:00", tz="UTC")
        q = Quote("MSFT", 370.0, 370.05, 200, 150, ts)
        with pytest.raises((dataclasses.FrozenInstanceError, TypeError, AttributeError)):
            q.bid = 999.0  # type: ignore[misc]

    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(Quote)


# ---------------------------------------------------------------------------
# create_provider() factory
# ---------------------------------------------------------------------------

class TestCreateProvider:
    def test_returns_simulator_without_key(self, monkeypatch):
        monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
        from app.services.data_ingestion.simulator_provider import SimulatorProvider
        provider = create_provider()
        assert isinstance(provider, SimulatorProvider)

    def test_returns_massive_with_key(self, monkeypatch):
        monkeypatch.setenv("MASSIVE_API_KEY", "fake_key_for_test")
        from app.services.data_ingestion.massive_provider import MassiveProvider
        provider = create_provider()
        assert isinstance(provider, MassiveProvider)

    def test_simulator_without_key_accepts_db_session(self, monkeypatch):
        monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
        from app.services.data_ingestion.simulator_provider import SimulatorProvider
        provider = create_provider(db_session=None)
        assert isinstance(provider, SimulatorProvider)

    def test_massive_provider_uses_injected_key(self, monkeypatch):
        monkeypatch.setenv("MASSIVE_API_KEY", "injected_key_abc")
        from app.services.data_ingestion.massive_provider import MassiveProvider
        provider = create_provider()
        assert isinstance(provider, MassiveProvider)
        assert provider._key == "injected_key_abc"

    def test_factory_returns_market_data_provider(self, monkeypatch):
        monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
        from app.services.data_ingestion.market_interface import MarketDataProvider
        provider = create_provider()
        assert isinstance(provider, MarketDataProvider)
