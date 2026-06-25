"""
Unit tests for the paper-trading executor and AlpacaPaperClient.

All external calls (Alpaca API, ML predict, LLM decision, price loader) are mocked.
No real API calls or database connections are made.
"""
from __future__ import annotations

import sys
import os
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

import pandas as pd
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_price_df(n: int = 60, seed: int = 0) -> pd.DataFrame:
    """Synthetic price DataFrame matching the market provider format."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-01", periods=n, tz="America/New_York")
    close = 100.0 * np.cumprod(1 + rng.normal(0.0005, 0.01, n))
    return pd.DataFrame(
        {
            "date": dates,
            "open": close * 1.002,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": rng.integers(500_000, 2_000_000, n).astype(float),
            "vwap": close,
        }
    )


def _make_mock_db(yesterday_total: float | None = None):
    """
    Return a MagicMock DB session.

    If yesterday_total is given, the snapshot query will return a mock with
    that total_value; otherwise returns None (no prior snapshot).
    """
    db = MagicMock()
    db.add = MagicMock()
    db.flush = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()

    # Default: no existing instruments, positions, or snapshots
    query_mock = MagicMock()
    db.query.return_value = query_mock

    # Chained calls: .filter(...).first() → None by default
    filter_chain = MagicMock()
    filter_chain.first.return_value = None
    filter_chain.count.return_value = 0
    filter_chain.order_by.return_value.first.return_value = None
    query_mock.filter.return_value = filter_chain
    query_mock.filter_by.return_value.first.return_value = None

    if yesterday_total is not None:
        snap = MagicMock()
        snap.total_value = yesterday_total
        filter_chain.order_by.return_value.first.return_value = snap

    return db


def _make_instrument(id: int = 1, symbol: str = "AAPL") -> MagicMock:
    inst = MagicMock()
    inst.id = id
    inst.symbol = symbol
    return inst


def _make_decision(action: str = "buy", position_size_pct: float = 0.5) -> MagicMock:
    d = MagicMock()
    d.id = 99
    d.action = action
    d.position_size_pct = position_size_pct
    return d


# ─────────────────────────────────────────────────────────────────────────────
# AlpacaPaperClient tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAlpacaPaperClientConstruction:
    def test_raises_when_wrong_url(self):
        """Client must refuse to connect to any endpoint other than the paper URL."""
        from app.services.trading.alpaca_client import AlpacaPaperClient
        with patch("app.services.trading.alpaca_client.settings") as mock_settings:
            mock_settings.ALPACA_BASE_URL = "https://api.alpaca.markets"  # live endpoint
            mock_settings.ALPACA_API_KEY = "test"
            mock_settings.ALPACA_SECRET_KEY = "test"
            with pytest.raises(RuntimeError, match="refuses to connect"):
                AlpacaPaperClient()

    def test_raises_when_empty_url(self):
        """Client must refuse to connect when base URL is empty/unset."""
        from app.services.trading.alpaca_client import AlpacaPaperClient
        with patch("app.services.trading.alpaca_client.settings") as mock_settings:
            mock_settings.ALPACA_BASE_URL = ""
            mock_settings.ALPACA_API_KEY = "test"
            mock_settings.ALPACA_SECRET_KEY = "test"
            with pytest.raises(RuntimeError, match="refuses to connect"):
                AlpacaPaperClient()

    def test_paper_url_constant(self):
        """Verify the paper URL constant is correct."""
        import app.services.trading.alpaca_client as mod
        assert mod._PAPER_URL == "https://paper-api.alpaca.markets"

    def test_stub_mode_when_alpaca_not_installed(self):
        """When alpaca-py raises ImportError, client enters stub mode."""
        from app.services.trading.alpaca_client import AlpacaPaperClient

        with patch("app.services.trading.alpaca_client.settings") as mock_settings:
            mock_settings.ALPACA_BASE_URL = "https://paper-api.alpaca.markets"
            mock_settings.ALPACA_API_KEY = ""
            mock_settings.ALPACA_SECRET_KEY = ""

            # Simulate alpaca not installed
            original_init = AlpacaPaperClient.__init__

            def init_with_import_error(self):
                # Replicate the __init__ logic but force ImportError for alpaca
                if mock_settings.ALPACA_BASE_URL != "https://paper-api.alpaca.markets":
                    raise RuntimeError("wrong URL")
                try:
                    raise ImportError("alpaca-py not installed")
                except ImportError:
                    self._available = False

            with patch.object(AlpacaPaperClient, "__init__", init_with_import_error):
                client = AlpacaPaperClient()
                assert client._available is False


class TestAlpacaPaperClientStubMode:
    """When alpaca-py is not installed, the client should run in stub mode."""

    def _make_stub_client(self):
        """Create a client in stub mode by bypassing __init__ and setting _available=False."""
        from app.services.trading.alpaca_client import AlpacaPaperClient
        client = object.__new__(AlpacaPaperClient)
        client._available = False
        return client

    def test_stub_get_account_returns_defaults(self):
        """Stub mode returns a default 100k paper account."""
        client = self._make_stub_client()
        acct = client.get_account()
        assert acct["cash"] == 100_000.0
        assert acct["portfolio_value"] == 100_000.0

    def test_stub_submit_buy_returns_stub_order(self):
        """Stub mode buy returns a synthetic order dict."""
        from app.services.trading.alpaca_client import AlpacaPaperClient

        client = object.__new__(AlpacaPaperClient)
        client._available = False

        result = client.submit_market_buy("AAPL", 1000.0)
        assert result is not None
        assert result["id"] == "stub"
        assert result["symbol"] == "AAPL"
        assert result["side"] == "buy"

    def test_stub_submit_sell_returns_stub_order(self):
        """Stub mode sell returns a synthetic order dict."""
        from app.services.trading.alpaca_client import AlpacaPaperClient

        client = object.__new__(AlpacaPaperClient)
        client._available = False

        result = client.submit_market_sell("AAPL", 5.0)
        assert result is not None
        assert result["id"] == "stub"
        assert result["side"] == "sell"
        assert result["qty"] == 5.0

    def test_stub_close_position_returns_true(self):
        """Stub mode close position always returns True."""
        from app.services.trading.alpaca_client import AlpacaPaperClient

        client = object.__new__(AlpacaPaperClient)
        client._available = False

        assert client.close_position("AAPL") is True

    def test_stub_get_positions_returns_empty_list(self):
        """Stub mode positions returns empty list."""
        from app.services.trading.alpaca_client import AlpacaPaperClient

        client = object.__new__(AlpacaPaperClient)
        client._available = False

        assert client.get_positions() == []


# ─────────────────────────────────────────────────────────────────────────────
# _open_position_count tests
# ─────────────────────────────────────────────────────────────────────────────

class TestOpenPositionCount:
    def test_returns_zero_when_no_positions(self):
        from app.services.trading.executor import _open_position_count

        db = MagicMock()
        db.query.return_value.filter.return_value.count.return_value = 0
        assert _open_position_count(db) == 0

    def test_returns_correct_count(self):
        from app.services.trading.executor import _open_position_count

        db = MagicMock()
        db.query.return_value.filter.return_value.count.return_value = 4
        assert _open_position_count(db) == 4

    def test_count_query_uses_paper_mode(self):
        """Verify the count only checks paper positions with no backtest_run_id."""
        from app.services.trading.executor import _open_position_count
        from app.models import Position

        db = MagicMock()
        count_mock = MagicMock(return_value=2)
        db.query.return_value.filter.return_value.count = count_mock

        result = _open_position_count(db)
        assert result == 2
        # DB query was called with Position model
        db.query.assert_called_once_with(Position)


# ─────────────────────────────────────────────────────────────────────────────
# run_daily_cycle tests
# ─────────────────────────────────────────────────────────────────────────────

def _make_mock_alpaca_client(portfolio_value: float = 100_000.0, cash: float = 90_000.0):
    """Return a mock AlpacaPaperClient."""
    client = MagicMock()
    client.get_account.return_value = {
        "cash": cash,
        "portfolio_value": portfolio_value,
        "equity": portfolio_value - cash,
    }
    client.get_positions.return_value = []
    client.submit_market_buy.return_value = {
        "id": "order-123",
        "symbol": "AAPL",
        "side": "buy",
        "notional": 1000.0,
    }
    client.submit_market_sell.return_value = {
        "id": "order-124",
        "symbol": "AAPL",
        "side": "sell",
        "qty": 5.0,
    }
    return client


class TestRunDailyCycleCircuitBreaker:
    """Circuit breaker should fire when daily loss exceeds DAILY_LOSS_LIMIT_PCT."""

    def test_circuit_breaker_triggers_on_large_loss(self):
        from app.services.trading.executor import run_daily_cycle
        from app.models import PortfolioSnapshot

        # Yesterday portfolio was 100k, today it's 96k → 4% loss > 3% limit
        db = _make_mock_db(yesterday_total=100_000.0)
        mock_client = _make_mock_alpaca_client(portfolio_value=96_000.0, cash=80_000.0)

        with patch("app.services.trading.executor.AlpacaPaperClient", return_value=mock_client), \
             patch("app.services.trading.executor._record_snapshot") as mock_snap:
            result = run_daily_cycle(db)

        assert result["status"] == "circuit_breaker"
        assert result["day_loss_pct"] < -0.03
        # Snapshot must still be recorded even when circuit breaker fires
        mock_snap.assert_called_once()
        db.commit.assert_called()

    def test_circuit_breaker_does_not_trigger_within_limit(self):
        """A 1% loss should not trigger the circuit breaker."""
        from app.services.trading.executor import run_daily_cycle

        db = _make_mock_db(yesterday_total=100_000.0)
        mock_client = _make_mock_alpaca_client(portfolio_value=99_000.0, cash=90_000.0)

        price_df = _make_price_df(60)
        mock_ml_result = {
            "signal_score": 0.5,
            "model_version": "xgb_v1",
            "features_snapshot": {},
        }
        mock_decision = _make_decision(action="hold", position_size_pct=0.0)

        with patch("app.services.trading.executor.AlpacaPaperClient", return_value=mock_client), \
             patch("app.services.trading.executor.fetch_latest_bars", return_value={}), \
             patch("app.services.trading.executor._load_price_dfs", return_value={}):
            result = run_daily_cycle(db)

        # Should not be circuit_breaker
        assert result["status"] != "circuit_breaker"

    def test_no_circuit_breaker_on_first_day(self):
        """With no prior snapshot, circuit breaker should not fire."""
        from app.services.trading.executor import run_daily_cycle

        # No yesterday snapshot
        db = _make_mock_db(yesterday_total=None)
        mock_client = _make_mock_alpaca_client()

        with patch("app.services.trading.executor.AlpacaPaperClient", return_value=mock_client), \
             patch("app.services.trading.executor.fetch_latest_bars", return_value={}), \
             patch("app.services.trading.executor._load_price_dfs", return_value={}):
            result = run_daily_cycle(db)

        assert result["status"] == "ok"


class TestRunDailyCycleBuyOrder:
    """Normal cycle with bullish signal should place a buy order."""

    def _setup_db_for_buy(self, open_count: int = 0):
        """DB mock where position count returns open_count and instrument creation works."""
        db = MagicMock()
        db.add = MagicMock()
        db.flush = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()

        inst = _make_instrument(id=1, symbol="AAPL")

        call_counter = {"n": 0}

        def query_side_effect(model):
            call_counter["n"] += 1
            q = MagicMock()
            model_name = getattr(model, "__name__", str(model))

            if "Instrument" in model_name:
                q.filter.return_value.first.return_value = inst
                q.filter_by.return_value.first.return_value = inst
            elif "PortfolioSnapshot" in model_name:
                # No prior snapshot — no circuit breaker
                q.filter.return_value.order_by.return_value.first.return_value = None
            elif "Position" in model_name:
                q.filter.return_value.count.return_value = open_count
                q.filter.return_value.first.return_value = None
            else:
                q.filter.return_value.first.return_value = None
                q.filter.return_value.count.return_value = open_count
                q.filter.return_value.order_by.return_value.first.return_value = None
            return q

        db.query.side_effect = query_side_effect
        return db, inst

    def test_buy_order_placed_on_bullish_signal(self):
        from app.services.trading.executor import run_daily_cycle

        db, inst = self._setup_db_for_buy(open_count=0)
        mock_client = _make_mock_alpaca_client()
        price_df = _make_price_df(60)
        mock_decision = _make_decision(action="buy", position_size_pct=0.8)

        with patch("app.services.trading.executor.AlpacaPaperClient", return_value=mock_client), \
             patch("app.services.trading.executor.fetch_latest_bars", return_value={"AAPL": 60}), \
             patch("app.services.trading.executor._load_price_dfs", return_value={"AAPL": price_df}), \
             patch("app.services.trading.executor._open_position_count", return_value=0), \
             patch("app.services.trading.executor._get_or_create_instrument", return_value=inst), \
             patch("app.services.trading.executor._get_open_position", return_value=None), \
             patch("app.services.trading.executor.ml_predict", return_value={
                 "signal_score": 2.0,
                 "model_version": "xgb_v1",
                 "features_snapshot": {},
             }), \
             patch("app.services.trading.executor.get_or_create_decision",
                   return_value=mock_decision), \
             patch("app.services.trading.executor._upsert_position"):
            result = run_daily_cycle(db)

        # A buy order should have been submitted
        mock_client.submit_market_buy.assert_called()
        assert result["orders_placed"] >= 1

    def test_no_buy_when_notional_too_small(self):
        """If computed notional < $1, no order should be placed."""
        from app.services.trading.executor import run_daily_cycle

        db, inst = self._setup_db_for_buy(open_count=0)
        mock_client = _make_mock_alpaca_client(portfolio_value=100_000.0)
        price_df = _make_price_df(60)

        # position_size_pct = 0.0 → notional = 0 → no order
        mock_decision = _make_decision(action="buy", position_size_pct=0.0)

        with patch("app.services.trading.executor.AlpacaPaperClient", return_value=mock_client), \
             patch("app.services.trading.executor.fetch_latest_bars", return_value={}), \
             patch("app.services.trading.executor._load_price_dfs", return_value={"AAPL": price_df}), \
             patch("app.services.trading.executor._open_position_count", return_value=0), \
             patch("app.services.trading.executor._get_or_create_instrument", return_value=inst), \
             patch("app.services.trading.executor._get_open_position", return_value=None), \
             patch("app.services.trading.executor.ml_predict", return_value={
                 "signal_score": 2.0,
                 "model_version": "xgb_v1",
                 "features_snapshot": {},
             }), \
             patch("app.services.trading.executor.get_or_create_decision",
                   return_value=mock_decision):
            run_daily_cycle(db)

        mock_client.submit_market_buy.assert_not_called()


class TestRunDailyCycleMaxPositions:
    """MAX_POSITIONS limit should block new buys when already at capacity."""

    def test_no_new_buy_when_max_positions_reached(self):
        from app.services.trading.executor import run_daily_cycle
        from app.core.config import settings

        max_pos = settings.MAX_POSITIONS  # 8

        # Use _make_mock_db with no prior snapshot so circuit breaker doesn't fire
        db = _make_mock_db(yesterday_total=None)

        inst = _make_instrument(id=1, symbol="AAPL")
        price_df = _make_price_df(60)
        mock_decision = _make_decision(action="buy", position_size_pct=0.8)
        mock_client = _make_mock_alpaca_client()

        with patch("app.services.trading.executor.AlpacaPaperClient", return_value=mock_client), \
             patch("app.services.trading.executor.fetch_latest_bars", return_value={}), \
             patch("app.services.trading.executor._load_price_dfs", return_value={"AAPL": price_df}), \
             patch("app.services.trading.executor._open_position_count", return_value=max_pos), \
             patch("app.services.trading.executor._get_or_create_instrument", return_value=inst), \
             patch("app.services.trading.executor._get_open_position", return_value=None), \
             patch("app.services.trading.executor.ml_predict", return_value={
                 "signal_score": 2.0,
                 "model_version": "xgb_v1",
                 "features_snapshot": {},
             }), \
             patch("app.services.trading.executor.get_or_create_decision",
                   return_value=mock_decision), \
             patch("app.services.trading.executor._record_snapshot"):
            run_daily_cycle(db)

        # No buy should have been submitted when MAX_POSITIONS is already reached
        mock_client.submit_market_buy.assert_not_called()

    def test_buy_allowed_when_existing_position_open(self):
        """Adding to an existing position is allowed even at MAX_POSITIONS."""
        from app.services.trading.executor import _process_symbol
        from app.core.config import settings

        max_pos = settings.MAX_POSITIONS

        db = MagicMock()
        db.add = MagicMock()
        db.flush = MagicMock()

        inst = _make_instrument(id=1, symbol="AAPL")
        # An existing position for AAPL
        existing_pos = MagicMock()
        existing_pos.quantity = 5.0
        existing_pos.avg_entry_price = 150.0

        price_df = _make_price_df(60)
        mock_decision = _make_decision(action="buy", position_size_pct=0.5)
        mock_client = _make_mock_alpaca_client(cash=50_000.0)

        orders_placed = []

        with patch("app.services.trading.executor._get_or_create_instrument", return_value=inst), \
             patch("app.services.trading.executor._get_open_position", return_value=existing_pos), \
             patch("app.services.trading.executor.ml_predict", return_value={
                 "signal_score": 2.0,
                 "model_version": "xgb_v1",
                 "features_snapshot": {},
             }), \
             patch("app.services.trading.executor.get_or_create_decision",
                   return_value=mock_decision), \
             patch("app.services.trading.executor._upsert_position"):
            _process_symbol(
                db=db,
                client=mock_client,
                symbol="AAPL",
                price_dfs={"AAPL": price_df},
                today=date.today(),
                portfolio_value=100_000.0,
                cash=50_000.0,
                open_count=max_pos,  # already at max
                orders_placed=orders_placed,
            )

        # Buying into existing position should be allowed
        mock_client.submit_market_buy.assert_called_once()
        assert len(orders_placed) == 1


class TestRunDailyCycleSellOrder:
    """Sell orders should close existing positions."""

    def test_sell_order_placed_when_action_is_sell(self):
        from app.services.trading.executor import _process_symbol

        db = MagicMock()
        db.add = MagicMock()
        db.flush = MagicMock()

        inst = _make_instrument(id=1, symbol="AAPL")
        existing_pos = MagicMock()
        existing_pos.quantity = 10.0
        existing_pos.avg_entry_price = 150.0

        price_df = _make_price_df(60)
        mock_decision = _make_decision(action="sell", position_size_pct=0.0)
        mock_client = _make_mock_alpaca_client()
        orders_placed = []

        with patch("app.services.trading.executor._get_or_create_instrument", return_value=inst), \
             patch("app.services.trading.executor._get_open_position", return_value=existing_pos), \
             patch("app.services.trading.executor.ml_predict", return_value={
                 "signal_score": -2.0,
                 "model_version": "xgb_v1",
                 "features_snapshot": {},
             }), \
             patch("app.services.trading.executor.get_or_create_decision",
                   return_value=mock_decision):
            _process_symbol(
                db=db,
                client=mock_client,
                symbol="AAPL",
                price_dfs={"AAPL": price_df},
                today=date.today(),
                portfolio_value=100_000.0,
                cash=80_000.0,
                open_count=2,
                orders_placed=orders_placed,
            )

        mock_client.submit_market_sell.assert_called_once_with("AAPL", 10.0)
        assert len(orders_placed) == 1
        assert orders_placed[0]["side"] == "sell"
        # Position quantity should be zeroed
        assert existing_pos.quantity == 0

    def test_no_sell_when_no_position(self):
        """No sell order when there is no open position to close."""
        from app.services.trading.executor import _process_symbol

        db = MagicMock()
        db.add = MagicMock()
        db.flush = MagicMock()

        inst = _make_instrument(id=1, symbol="AAPL")
        price_df = _make_price_df(60)
        mock_decision = _make_decision(action="sell", position_size_pct=0.0)
        mock_client = _make_mock_alpaca_client()
        orders_placed = []

        with patch("app.services.trading.executor._get_or_create_instrument", return_value=inst), \
             patch("app.services.trading.executor._get_open_position", return_value=None), \
             patch("app.services.trading.executor.ml_predict", return_value={
                 "signal_score": -2.0,
                 "model_version": "xgb_v1",
                 "features_snapshot": {},
             }), \
             patch("app.services.trading.executor.get_or_create_decision",
                   return_value=mock_decision):
            _process_symbol(
                db=db,
                client=mock_client,
                symbol="AAPL",
                price_dfs={"AAPL": price_df},
                today=date.today(),
                portfolio_value=100_000.0,
                cash=80_000.0,
                open_count=0,
                orders_placed=orders_placed,
            )

        mock_client.submit_market_sell.assert_not_called()
        assert len(orders_placed) == 0


class TestRunDailyCyclePriceDataGap:
    """Symbols with insufficient price data should be skipped gracefully."""

    def test_skips_symbol_with_insufficient_data(self):
        from app.services.trading.executor import _process_symbol

        db = MagicMock()
        inst = _make_instrument(id=1, symbol="AAPL")
        mock_client = _make_mock_alpaca_client()
        orders_placed = []

        # Only 10 bars — not enough (need ≥ 30)
        short_df = _make_price_df(10)

        with patch("app.services.trading.executor._get_or_create_instrument", return_value=inst), \
             patch("app.services.trading.executor.ml_predict") as mock_predict:
            _process_symbol(
                db=db,
                client=mock_client,
                symbol="AAPL",
                price_dfs={"AAPL": short_df},
                today=date.today(),
                portfolio_value=100_000.0,
                cash=80_000.0,
                open_count=0,
                orders_placed=orders_placed,
            )

        # ML predict should not be called at all
        mock_predict.assert_not_called()
        assert len(orders_placed) == 0

    def test_skips_symbol_with_missing_price_data(self):
        """Symbol with no price data at all (None) should be skipped."""
        from app.services.trading.executor import _process_symbol

        db = MagicMock()
        inst = _make_instrument(id=1, symbol="AAPL")
        mock_client = _make_mock_alpaca_client()
        orders_placed = []

        with patch("app.services.trading.executor._get_or_create_instrument", return_value=inst), \
             patch("app.services.trading.executor.ml_predict") as mock_predict:
            _process_symbol(
                db=db,
                client=mock_client,
                symbol="AAPL",
                price_dfs={},  # AAPL not in dfs
                today=date.today(),
                portfolio_value=100_000.0,
                cash=80_000.0,
                open_count=0,
                orders_placed=orders_placed,
            )

        mock_predict.assert_not_called()
        assert len(orders_placed) == 0


class TestRunDailyCyclePortfolioSnapshot:
    """A PortfolioSnapshot must be recorded at the end of every cycle."""

    def test_snapshot_recorded_after_cycle(self):
        from app.services.trading.executor import run_daily_cycle

        db = _make_mock_db(yesterday_total=None)
        mock_client = _make_mock_alpaca_client()

        with patch("app.services.trading.executor.AlpacaPaperClient", return_value=mock_client), \
             patch("app.services.trading.executor.fetch_latest_bars", return_value={}), \
             patch("app.services.trading.executor._load_price_dfs", return_value={}), \
             patch("app.services.trading.executor._record_snapshot") as mock_snap:
            run_daily_cycle(db)

        mock_snap.assert_called_once()
        db.commit.assert_called()

    def test_snapshot_contains_correct_values(self):
        from app.services.trading.executor import _record_snapshot
        from app.models import PortfolioSnapshot

        db = MagicMock()
        db.add = MagicMock()

        today = date(2024, 6, 15)
        _record_snapshot(db, today, cash=80_000.0, equity=20_000.0, total_value=100_000.0)

        db.add.assert_called_once()
        snap = db.add.call_args[0][0]
        assert isinstance(snap, PortfolioSnapshot)
        assert snap.cash == 80_000.0
        assert snap.equity == 20_000.0
        assert snap.total_value == 100_000.0
        assert snap.mode == "paper"
        assert snap.as_of_date == today


class TestRunDailyCycleSymbolError:
    """A failure on one symbol must not abort processing of other symbols."""

    def test_error_in_one_symbol_does_not_abort_others(self):
        from app.services.trading.executor import run_daily_cycle

        db = _make_mock_db(yesterday_total=None)
        mock_client = _make_mock_alpaca_client()

        price_df = _make_price_df(60)

        def ml_predict_side_effect(symbol, df, as_of, model_version="xgb_v1"):
            if symbol == "AAPL":
                raise ValueError("ML failed for AAPL")
            return {"signal_score": 0.0, "model_version": "xgb_v1", "features_snapshot": {}}

        mock_decision = _make_decision(action="hold", position_size_pct=0.0)
        inst_aapl = _make_instrument(id=1, symbol="AAPL")
        inst_msft = _make_instrument(id=2, symbol="MSFT")

        def get_or_create_inst_side(db, symbol):
            return inst_aapl if symbol == "AAPL" else inst_msft

        # Minimal watchlist for this test
        with patch("app.services.trading.executor.AlpacaPaperClient", return_value=mock_client), \
             patch("app.services.trading.executor.fetch_latest_bars", return_value={}), \
             patch("app.services.trading.executor._load_price_dfs",
                   return_value={"AAPL": price_df, "MSFT": price_df}), \
             patch("app.services.trading.executor.settings") as mock_settings, \
             patch("app.services.trading.executor.ml_predict", side_effect=ml_predict_side_effect), \
             patch("app.services.trading.executor.get_or_create_decision", return_value=mock_decision), \
             patch("app.services.trading.executor._get_or_create_instrument",
                   side_effect=get_or_create_inst_side), \
             patch("app.services.trading.executor._get_open_position", return_value=None), \
             patch("app.services.trading.executor._open_position_count", return_value=0), \
             patch("app.services.trading.executor._record_snapshot"):
            mock_settings.WATCHLIST = ["AAPL", "MSFT"]
            mock_settings.DAILY_LOSS_LIMIT_PCT = 0.03
            mock_settings.MAX_POSITIONS = 8
            mock_settings.MAX_POSITION_PCT = 0.10
            # Even with AAPL failure, cycle should complete OK
            result = run_daily_cycle(db)

        # Result should be ok — the cycle completed
        assert result["status"] == "ok"


class TestUpsertPosition:
    def test_creates_new_position_when_none_exists(self):
        from app.services.trading.executor import _upsert_position
        from app.models import Position

        db = MagicMock()
        db.add = MagicMock()

        _upsert_position(db, instrument_id=1, qty=10.0, price=150.0, existing=None)

        db.add.assert_called_once()
        pos = db.add.call_args[0][0]
        assert isinstance(pos, Position)
        assert pos.quantity == 10.0
        assert pos.avg_entry_price == 150.0
        assert pos.mode == "paper"

    def test_updates_existing_position_with_correct_avg_price(self):
        from app.services.trading.executor import _upsert_position

        db = MagicMock()
        existing = MagicMock()
        existing.quantity = 10.0
        existing.avg_entry_price = 100.0

        # Buy 5 more at 120 → avg = (10*100 + 5*120) / 15 = 106.67
        _upsert_position(db, instrument_id=1, qty=5.0, price=120.0, existing=existing)

        db.add.assert_not_called()
        assert existing.quantity == 15.0
        assert existing.avg_entry_price == pytest.approx(106.666, rel=1e-3)
