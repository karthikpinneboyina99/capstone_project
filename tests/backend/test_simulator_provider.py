"""
Unit tests for SimulatorProvider.

Verifies that SimulatorProvider correctly wraps MarketSimulator and exposes
the full MarketDataProvider interface with correct return types.
"""
from datetime import date

import pandas as pd
import pytest

from app.services.data_ingestion.simulator_provider import SimulatorProvider
from app.services.data_ingestion.market_interface import Bar, Quote, MarketDataProvider

EXPECTED_COLS = ["date", "open", "high", "low", "close", "volume", "vwap"]

# Shared provider instance (no DB, fixed seed)
PROVIDER = SimulatorProvider(db_session=None, seed=42)


class TestIsMarketDataProvider:
    def test_implements_interface(self):
        assert isinstance(PROVIDER, MarketDataProvider)


# ---------------------------------------------------------------------------
# get_bars
# ---------------------------------------------------------------------------

class TestGetBars:
    def test_returns_dict_keyed_by_ticker(self):
        result = PROVIDER.get_bars(
            ["AAPL", "MSFT"], date(2023, 1, 1), date(2023, 3, 31)
        )
        assert isinstance(result, dict)
        assert set(result.keys()) == {"AAPL", "MSFT"}

    def test_values_are_dataframes(self):
        result = PROVIDER.get_bars(["SPY"], date(2023, 1, 1), date(2023, 3, 31))
        assert isinstance(result["SPY"], pd.DataFrame)

    def test_correct_columns(self):
        result = PROVIDER.get_bars(["AAPL"], date(2023, 1, 1), date(2023, 3, 31))
        assert list(result["AAPL"].columns) == EXPECTED_COLS

    def test_non_empty_for_valid_range(self):
        result = PROVIDER.get_bars(["NVDA"], date(2023, 1, 1), date(2023, 6, 30))
        assert len(result["NVDA"]) > 0

    def test_no_lookahead(self):
        to = date(2023, 6, 15)
        result = PROVIDER.get_bars(["AAPL"], date(2023, 1, 1), to)
        assert result["AAPL"]["date"].dt.date.max() <= to

    def test_ohlc_invariants(self):
        df = PROVIDER.get_bars(["MSFT"], date(2022, 1, 1), date(2022, 12, 31))["MSFT"]
        assert (df["high"] >= df["close"]).all()
        assert (df["low"] <= df["close"]).all()
        assert (df["close"] > 0).all()

    def test_multiple_tickers_independent(self):
        result = PROVIDER.get_bars(
            ["AAPL", "TSLA"], date(2023, 1, 1), date(2023, 6, 30)
        )
        # Each ticker has its own path — closes should differ
        assert not result["AAPL"]["close"].equals(result["TSLA"]["close"])

    def test_single_ticker_list(self):
        result = PROVIDER.get_bars(["QQQ"], date(2023, 3, 1), date(2023, 3, 31))
        assert "QQQ" in result

    def test_empty_ticker_list(self):
        result = PROVIDER.get_bars([], date(2023, 1, 1), date(2023, 3, 31))
        assert result == {}

    def test_deterministic_across_calls(self):
        r1 = PROVIDER.get_bars(["AAPL"], date(2023, 1, 1), date(2023, 6, 30))
        r2 = PROVIDER.get_bars(["AAPL"], date(2023, 1, 1), date(2023, 6, 30))
        pd.testing.assert_frame_equal(r1["AAPL"], r2["AAPL"])


# ---------------------------------------------------------------------------
# get_snapshot
# ---------------------------------------------------------------------------

class TestGetSnapshot:
    def test_returns_dict_of_bars(self):
        result = PROVIDER.get_snapshot(["AAPL", "MSFT"])
        assert isinstance(result, dict)
        for v in result.values():
            assert isinstance(v, Bar)

    def test_keys_match_tickers(self):
        result = PROVIDER.get_snapshot(["AAPL", "NVDA"])
        assert set(result.keys()) == {"AAPL", "NVDA"}

    def test_bar_ticker_field_matches(self):
        result = PROVIDER.get_snapshot(["SPY"])
        assert result["SPY"].ticker == "SPY"

    def test_positive_close(self):
        result = PROVIDER.get_snapshot(["AAPL", "MSFT", "NVDA"])
        for ticker, bar in result.items():
            assert bar.close > 0, f"{ticker} close not positive"

    def test_ohlc_invariants(self):
        result = PROVIDER.get_snapshot(["AAPL"])
        bar = result["AAPL"]
        assert bar.high >= bar.open
        assert bar.high >= bar.close
        assert bar.low <= bar.open
        assert bar.low <= bar.close


# ---------------------------------------------------------------------------
# get_latest_quote
# ---------------------------------------------------------------------------

class TestGetLatestQuote:
    def test_returns_dict_of_quotes(self):
        result = PROVIDER.get_latest_quote(["AAPL", "MSFT"])
        assert isinstance(result, dict)
        for v in result.values():
            assert isinstance(v, Quote)

    def test_keys_match_tickers(self):
        result = PROVIDER.get_latest_quote(["AAPL", "SPY"])
        assert set(result.keys()) == {"AAPL", "SPY"}

    def test_bid_less_than_ask(self):
        result = PROVIDER.get_latest_quote(["AAPL", "MSFT", "NVDA"])
        for ticker, q in result.items():
            assert q.bid < q.ask, f"{ticker}: bid >= ask"

    def test_quote_ticker_field_matches(self):
        result = PROVIDER.get_latest_quote(["QQQ"])
        assert result["QQQ"].ticker == "QQQ"

    def test_positive_bid_ask(self):
        result = PROVIDER.get_latest_quote(["AAPL"])
        q = result["AAPL"]
        assert q.bid > 0
        assert q.ask > 0

    def test_timestamp_tz_aware(self):
        result = PROVIDER.get_latest_quote(["AAPL"])
        assert result["AAPL"].timestamp.tz is not None


# ---------------------------------------------------------------------------
# get_daily_market_summary
# ---------------------------------------------------------------------------

class TestGetDailyMarketSummary:
    def test_returns_dict_of_bars(self):
        result = PROVIDER.get_daily_market_summary(date(2023, 6, 15))
        assert isinstance(result, dict)
        for v in result.values():
            assert isinstance(v, Bar)

    def test_non_empty(self):
        result = PROVIDER.get_daily_market_summary(date(2023, 6, 15))
        assert len(result) > 0

    def test_positive_closes(self):
        result = PROVIDER.get_daily_market_summary(date(2023, 6, 15))
        for ticker, bar in result.items():
            assert bar.close > 0, f"{ticker} close <= 0"

    def test_covers_known_watchlist_tickers(self):
        result = PROVIDER.get_daily_market_summary(date(2023, 6, 15))
        expected = {"AAPL", "MSFT", "NVDA", "SPY", "QQQ"}
        for ticker in expected:
            assert ticker in result, f"{ticker} missing from daily summary"


# ---------------------------------------------------------------------------
# Seed isolation
# ---------------------------------------------------------------------------

class TestSeedIsolation:
    def test_different_seeds_different_data(self):
        p1 = SimulatorProvider(db_session=None, seed=1)
        p2 = SimulatorProvider(db_session=None, seed=2)
        df1 = p1.get_bars(["AAPL"], date(2023, 1, 1), date(2023, 6, 30))["AAPL"]
        df2 = p2.get_bars(["AAPL"], date(2023, 1, 1), date(2023, 6, 30))["AAPL"]
        assert not df1["close"].equals(df2["close"])

    def test_same_seed_same_data(self):
        p1 = SimulatorProvider(db_session=None, seed=42)
        p2 = SimulatorProvider(db_session=None, seed=42)
        df1 = p1.get_bars(["AAPL"], date(2023, 1, 1), date(2023, 6, 30))["AAPL"]
        df2 = p2.get_bars(["AAPL"], date(2023, 1, 1), date(2023, 6, 30))["AAPL"]
        pd.testing.assert_frame_equal(df1, df2)
