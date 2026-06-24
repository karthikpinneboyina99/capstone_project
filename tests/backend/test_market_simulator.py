"""
Unit tests for MarketSimulator.

All tests run in synthetic mode (no DB session). Covers:
  - DataFrame schema
  - No-lookahead guarantee
  - OHLC invariants
  - Determinism / reproducibility
  - Unknown ticker fallback
  - Positive prices
  - Ascending date order
  - Business-days-only output
  - latest_bar / latest_quote helpers
  - daily_summary
  - DB replay mode (mocked session)
"""
from datetime import date, timedelta
from unittest.mock import MagicMock

import pandas as pd
import pytest

from app.services.data_ingestion.market_simulator import MarketSimulator, _KNOWN
from app.services.data_ingestion.market_interface import Bar, Quote

# Shared simulator instance (synthetic mode, fixed seed)
SIM = MarketSimulator(db_session=None, seed=42)

EXPECTED_COLS = ["date", "open", "high", "low", "close", "volume", "vwap"]


# ---------------------------------------------------------------------------
# DataFrame schema
# ---------------------------------------------------------------------------

class TestSchema:
    def test_correct_columns(self):
        df = SIM.get_bars("AAPL", date(2023, 1, 1), date(2023, 3, 31))
        assert list(df.columns) == EXPECTED_COLS

    def test_non_empty_for_valid_range(self):
        df = SIM.get_bars("AAPL", date(2023, 1, 1), date(2023, 3, 31))
        assert len(df) > 0

    def test_date_column_is_datetime(self):
        df = SIM.get_bars("MSFT", date(2023, 1, 1), date(2023, 3, 31))
        assert pd.api.types.is_datetime64_any_dtype(df["date"])

    def test_date_column_is_timezone_aware(self):
        df = SIM.get_bars("SPY", date(2023, 1, 1), date(2023, 3, 31))
        assert df["date"].dt.tz is not None

    def test_numeric_price_columns(self):
        df = SIM.get_bars("AAPL", date(2023, 1, 1), date(2023, 3, 31))
        for col in ["open", "high", "low", "close"]:
            assert pd.api.types.is_numeric_dtype(df[col]), f"{col} is not numeric"

    def test_volume_is_integer_like(self):
        df = SIM.get_bars("AAPL", date(2023, 1, 1), date(2023, 3, 31))
        assert pd.api.types.is_integer_dtype(df["volume"])


# ---------------------------------------------------------------------------
# No-lookahead guarantee
# ---------------------------------------------------------------------------

class TestNoLookahead:
    def test_max_date_does_not_exceed_to_date(self):
        to = date(2023, 6, 15)
        df = SIM.get_bars("AAPL", date(2023, 1, 1), to)
        assert df["date"].dt.date.max() <= to

    def test_from_date_filter_applied(self):
        from_d = date(2023, 4, 1)
        df = SIM.get_bars("AAPL", from_d, date(2023, 6, 30))
        assert df["date"].dt.date.min() >= from_d

    def test_single_day_range(self):
        # 2023-03-01 is a Wednesday (business day)
        df = SIM.get_bars("AAPL", date(2023, 3, 1), date(2023, 3, 1))
        assert len(df) == 1
        assert df.iloc[0]["date"].date() == date(2023, 3, 1)


# ---------------------------------------------------------------------------
# OHLC invariants
# ---------------------------------------------------------------------------

class TestOHLCInvariants:
    def setup_method(self):
        self.df = SIM.get_bars("MSFT", date(2022, 1, 1), date(2022, 12, 31))

    def test_high_gte_open(self):
        assert (self.df["high"] >= self.df["open"]).all()

    def test_high_gte_close(self):
        assert (self.df["high"] >= self.df["close"]).all()

    def test_low_lte_open(self):
        assert (self.df["low"] <= self.df["open"]).all()

    def test_low_lte_close(self):
        assert (self.df["low"] <= self.df["close"]).all()

    def test_positive_close(self):
        assert (self.df["close"] > 0).all()

    def test_positive_open(self):
        assert (self.df["open"] > 0).all()

    def test_positive_high(self):
        assert (self.df["high"] > 0).all()

    def test_positive_low(self):
        assert (self.df["low"] > 0).all()

    def test_low_lte_high(self):
        assert (self.df["low"] <= self.df["high"]).all()

    def test_positive_volume(self):
        assert (self.df["volume"] > 0).all()


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_same_seed_same_data(self):
        df1 = SIM.get_bars("NVDA", date(2023, 1, 1), date(2023, 6, 30))
        df2 = MarketSimulator(seed=42).get_bars("NVDA", date(2023, 1, 1), date(2023, 6, 30))
        pd.testing.assert_frame_equal(df1, df2)

    def test_different_seed_different_data(self):
        df1 = SIM.get_bars("AAPL", date(2023, 1, 1), date(2023, 6, 30))
        df2 = MarketSimulator(seed=99).get_bars("AAPL", date(2023, 1, 1), date(2023, 6, 30))
        assert not df1["close"].equals(df2["close"])

    def test_repeated_calls_identical(self):
        df1 = SIM.get_bars("SPY", date(2022, 6, 1), date(2022, 9, 30))
        df2 = SIM.get_bars("SPY", date(2022, 6, 1), date(2022, 9, 30))
        pd.testing.assert_frame_equal(df1, df2)


# ---------------------------------------------------------------------------
# Unknown ticker fallback
# ---------------------------------------------------------------------------

class TestUnknownTicker:
    def test_returns_non_empty_df(self):
        df = SIM.get_bars("XYZFAKE", date(2023, 1, 1), date(2023, 3, 31))
        assert len(df) > 0

    def test_correct_schema(self):
        df = SIM.get_bars("XYZFAKE", date(2023, 1, 1), date(2023, 3, 31))
        assert list(df.columns) == EXPECTED_COLS

    def test_ohlc_invariants_hold(self):
        df = SIM.get_bars("UNKNOWN999", date(2023, 1, 1), date(2023, 6, 30))
        assert (df["high"] >= df["close"]).all()
        assert (df["low"] <= df["close"]).all()
        assert (df["close"] > 0).all()

    def test_different_tickers_get_different_paths(self):
        df1 = SIM.get_bars("TICKER_A", date(2023, 1, 1), date(2023, 6, 30))
        df2 = SIM.get_bars("TICKER_B", date(2023, 1, 1), date(2023, 6, 30))
        # Very unlikely to be equal with different hash-seeds
        assert not df1["close"].equals(df2["close"])


# ---------------------------------------------------------------------------
# Business-days only
# ---------------------------------------------------------------------------

class TestBusinessDaysOnly:
    def test_no_weekends_in_output(self):
        df = SIM.get_bars("AAPL", date(2023, 1, 1), date(2023, 6, 30))
        day_of_week = df["date"].dt.dayofweek
        # 0=Monday, 4=Friday; Saturday=5, Sunday=6
        assert (day_of_week <= 4).all(), "Weekend dates found in output"

    def test_ascending_order(self):
        df = SIM.get_bars("MSFT", date(2023, 1, 1), date(2023, 6, 30))
        dates = df["date"].values
        assert (dates[1:] > dates[:-1]).all(), "Dates not in ascending order"


# ---------------------------------------------------------------------------
# latest_bar
# ---------------------------------------------------------------------------

class TestLatestBar:
    def test_returns_bar_instance(self):
        bar = SIM.latest_bar("AAPL")
        assert isinstance(bar, Bar)

    def test_bar_ticker_matches(self):
        bar = SIM.latest_bar("MSFT")
        assert bar.ticker == "MSFT"

    def test_bar_has_positive_close(self):
        bar = SIM.latest_bar("NVDA")
        assert bar.close > 0

    def test_ohlc_invariants(self):
        bar = SIM.latest_bar("SPY")
        assert bar.high >= bar.open
        assert bar.high >= bar.close
        assert bar.low <= bar.open
        assert bar.low <= bar.close

    def test_unknown_ticker_returns_bar(self):
        bar = SIM.latest_bar("XYZUNKNOWN")
        assert isinstance(bar, Bar)
        assert bar.close > 0


# ---------------------------------------------------------------------------
# latest_quote
# ---------------------------------------------------------------------------

class TestLatestQuote:
    def test_returns_quote_instance(self):
        q = SIM.latest_quote("AAPL")
        assert isinstance(q, Quote)

    def test_bid_less_than_ask(self):
        q = SIM.latest_quote("MSFT")
        assert q.bid < q.ask

    def test_ticker_matches(self):
        q = SIM.latest_quote("NVDA")
        assert q.ticker == "NVDA"

    def test_spread_is_small(self):
        # Synthetic spread is 2bps — should be < 1% of ask
        q = SIM.latest_quote("AAPL")
        spread_pct = (q.ask - q.bid) / q.ask
        assert spread_pct < 0.01

    def test_bid_ask_positive(self):
        q = SIM.latest_quote("SPY")
        assert q.bid > 0
        assert q.ask > 0

    def test_timestamp_is_utc(self):
        q = SIM.latest_quote("AAPL")
        assert q.timestamp.tz is not None


# ---------------------------------------------------------------------------
# daily_summary
# ---------------------------------------------------------------------------

class TestDailySummary:
    def test_returns_dict(self):
        summary = SIM.daily_summary(date(2023, 6, 15))
        assert isinstance(summary, dict)

    def test_covers_known_tickers(self):
        summary = SIM.daily_summary(date(2023, 6, 15))
        for ticker in _KNOWN:
            assert ticker in summary, f"{ticker} missing from daily summary"

    def test_all_values_are_bars(self):
        summary = SIM.daily_summary(date(2023, 6, 15))
        for ticker, bar in summary.items():
            assert isinstance(bar, Bar), f"{ticker} value is not a Bar"

    def test_positive_closes(self):
        summary = SIM.daily_summary(date(2023, 6, 15))
        for ticker, bar in summary.items():
            assert bar.close > 0, f"{ticker} has non-positive close"

    def test_respects_as_of_date_no_lookahead(self):
        """Bars returned must not be dated after as_of — critical for backtester correctness."""
        as_of = date(2021, 6, 15)
        summary = SIM.daily_summary(as_of)
        for ticker, bar in summary.items():
            assert bar.date <= as_of, (
                f"{ticker} bar.date {bar.date} is after as_of {as_of} — lookahead detected"
            )

    def test_different_as_of_dates_differ(self):
        """Prices on different historical dates must differ (GBM paths are not constant)."""
        s1 = SIM.daily_summary(date(2021, 1, 4))
        s2 = SIM.daily_summary(date(2022, 1, 3))
        aapl_prices = {s1["AAPL"].close, s2["AAPL"].close}
        assert len(aapl_prices) == 2, "daily_summary returned same price for different dates"


# ---------------------------------------------------------------------------
# Edge cases — date range
# ---------------------------------------------------------------------------

class TestEdgeCaseDateRanges:
    def test_inverted_range_returns_empty(self):
        """from_date > to_date should return an empty DataFrame, not raise."""
        df = SIM.get_bars("AAPL", date(2023, 6, 30), date(2023, 1, 1))
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        assert list(df.columns) == EXPECTED_COLS

    def test_future_from_date_before_sim_origin_returns_empty(self):
        """Requesting a range entirely before _SIM_ORIGIN returns empty."""
        df = SIM.get_bars("AAPL", date(2019, 1, 1), date(2019, 12, 31))
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0


# ---------------------------------------------------------------------------
# DB replay mode (mocked SQLAlchemy session)
# ---------------------------------------------------------------------------

class TestDBReplayMode:
    def _make_mock_session(self, rows):
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = rows
        return mock_session

    def test_db_rows_returned_when_available(self):
        rows = [
            (pd.Timestamp("2023-01-03", tz="UTC"), 150.0, 155.0, 149.0, 153.5, 1_000_000),
            (pd.Timestamp("2023-01-04", tz="UTC"), 153.5, 157.0, 152.0, 156.0, 900_000),
        ]
        mock_session = self._make_mock_session(rows)
        sim = MarketSimulator(db_session=mock_session, seed=42)
        df = sim.get_bars("AAPL", date(2023, 1, 1), date(2023, 1, 31))
        assert len(df) == 2
        assert list(df.columns) == EXPECTED_COLS

    def test_falls_back_to_synthetic_when_db_empty(self):
        mock_session = self._make_mock_session([])
        sim = MarketSimulator(db_session=mock_session, seed=42)
        df = sim.get_bars("AAPL", date(2023, 1, 1), date(2023, 3, 31))
        # Should fall back to synthetic; non-empty with correct schema
        assert len(df) > 0
        assert list(df.columns) == EXPECTED_COLS

    def test_db_prices_preserved(self):
        rows = [
            (pd.Timestamp("2023-01-03", tz="UTC"), 150.0, 155.0, 149.0, 153.5, 1_000_000),
        ]
        mock_session = self._make_mock_session(rows)
        sim = MarketSimulator(db_session=mock_session, seed=42)
        df = sim.get_bars("AAPL", date(2023, 1, 1), date(2023, 1, 31))
        assert df.iloc[0]["close"] == pytest.approx(153.5)
        assert df.iloc[0]["open"] == pytest.approx(150.0)

    def test_db_vwap_is_none(self):
        rows = [
            (pd.Timestamp("2023-01-03", tz="UTC"), 150.0, 155.0, 149.0, 153.5, 1_000_000),
        ]
        mock_session = self._make_mock_session(rows)
        sim = MarketSimulator(db_session=mock_session, seed=42)
        df = sim.get_bars("AAPL", date(2023, 1, 1), date(2023, 1, 31))
        # DB replay sets vwap to None (price_bars table doesn't store it)
        assert df.iloc[0]["vwap"] is None

    def test_db_session_queried_with_correct_ticker(self):
        mock_session = self._make_mock_session([])
        sim = MarketSimulator(db_session=mock_session, seed=42)
        sim.get_bars("TSLA", date(2023, 1, 1), date(2023, 1, 31))
        call_kwargs = mock_session.execute.call_args[0][1]
        assert call_kwargs["ticker"] == "TSLA"
