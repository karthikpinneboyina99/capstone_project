"""
Unit tests for MassiveProvider.

All HTTP calls are mocked — no real API requests are made.
Covers:
  - Normal bars fetch (DataFrame shape, columns, values)
  - Pagination (next_url followed until absent)
  - Rate-limit retry (429 → backoff → success)
  - Max retries exhausted raises RuntimeError
  - API error in response body (status == "ERROR")
  - get_snapshot (day / prevDay fallback)
  - get_latest_quote (Starter plan — lastQuote absent)
  - get_daily_market_summary
  - Timestamp ms → tz-aware ET datetime conversion
  - Missing API key raises KeyError
  - MASSIVE_BASE_URL env override
"""
from datetime import date
from unittest.mock import MagicMock, call, patch

import pandas as pd
import pytest

from app.services.data_ingestion.massive_provider import MassiveProvider


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def provider():
    return MassiveProvider(api_key="test_api_key")


def _bar_result(t_ms=1672531200000, o=150.0, h=155.0, l=149.0, c=153.5, v=82_000_000, vw=152.7):
    return {"t": t_ms, "o": o, "h": h, "l": l, "c": c, "v": v, "vw": vw}


def _aggs_response(bars=None, next_url=None):
    body = {"status": "OK", "results": bars or [_bar_result()]}
    if next_url:
        body["next_url"] = next_url
    return body


def _mock_response(body: dict, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    resp.raise_for_status = MagicMock()
    return resp


def _mock_429():
    resp = MagicMock()
    resp.status_code = 429
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# get_bars — normal path
# ---------------------------------------------------------------------------

class TestGetBars:
    def test_returns_dataframe_for_each_ticker(self, provider):
        resp = _mock_response(_aggs_response())
        with patch("requests.get", return_value=resp):
            result = provider.get_bars(
                ["AAPL", "MSFT"], date(2023, 1, 1), date(2023, 3, 31)
            )
        assert set(result.keys()) == {"AAPL", "MSFT"}
        for df in result.values():
            assert isinstance(df, pd.DataFrame)

    def test_correct_columns(self, provider):
        resp = _mock_response(_aggs_response())
        with patch("requests.get", return_value=resp):
            result = provider.get_bars(["AAPL"], date(2023, 1, 1), date(2023, 3, 31))
        assert list(result["AAPL"].columns) == [
            "date", "open", "high", "low", "close", "volume", "vwap"
        ]

    def test_values_mapped_correctly(self, provider):
        bar = _bar_result(o=150.0, h=155.0, l=149.0, c=153.5, v=82_000_000, vw=152.7)
        resp = _mock_response(_aggs_response(bars=[bar]))
        with patch("requests.get", return_value=resp):
            result = provider.get_bars(["AAPL"], date(2023, 1, 1), date(2023, 3, 31))
        row = result["AAPL"].iloc[0]
        assert row["open"] == pytest.approx(150.0)
        assert row["high"] == pytest.approx(155.0)
        assert row["low"] == pytest.approx(149.0)
        assert row["close"] == pytest.approx(153.5)
        assert row["volume"] == 82_000_000
        assert row["vwap"] == pytest.approx(152.7)

    def test_empty_results_returns_empty_dataframe(self, provider):
        resp = _mock_response({"status": "OK", "results": []})
        with patch("requests.get", return_value=resp):
            result = provider.get_bars(["AAPL"], date(2023, 1, 1), date(2023, 3, 31))
        df = result["AAPL"]
        assert len(df) == 0
        assert list(df.columns) == [
            "date", "open", "high", "low", "close", "volume", "vwap"
        ]

    def test_null_results_key_treated_as_empty(self, provider):
        resp = _mock_response({"status": "OK", "results": None})
        with patch("requests.get", return_value=resp):
            result = provider.get_bars(["AAPL"], date(2023, 1, 1), date(2023, 3, 31))
        assert len(result["AAPL"]) == 0


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class TestPagination:
    def test_follows_next_url(self, provider):
        bar1 = _bar_result(t_ms=1672531200000, c=100.0)
        bar2 = _bar_result(t_ms=1672617600000, c=101.0)

        page1 = _mock_response(_aggs_response(bars=[bar1], next_url="https://api.polygon.io/next?cursor=abc"))
        page2 = _mock_response(_aggs_response(bars=[bar2]))

        with patch("requests.get", side_effect=[page1, page2]):
            result = provider.get_bars(["AAPL"], date(2023, 1, 1), date(2023, 1, 31))

        assert len(result["AAPL"]) == 2

    def test_all_pages_combined(self, provider):
        pages = [
            _mock_response(_aggs_response(
                bars=[_bar_result(t_ms=1672531200000 + i * 86400000, c=100.0 + i)],
                next_url=(f"https://api.polygon.io/next?cursor=p{i}" if i < 2 else None),
            ))
            for i in range(3)
        ]
        with patch("requests.get", side_effect=pages):
            result = provider.get_bars(["AAPL"], date(2023, 1, 1), date(2023, 1, 31))
        assert len(result["AAPL"]) == 3


# ---------------------------------------------------------------------------
# Rate-limit retry
# ---------------------------------------------------------------------------

class TestRetryLogic:
    def test_retries_on_429_then_succeeds(self, provider):
        responses = [_mock_429(), _mock_429(), _mock_response(_aggs_response())]
        with patch("requests.get", side_effect=responses), \
             patch("time.sleep"):  # don't actually sleep in tests
            result = provider.get_bars(["AAPL"], date(2023, 1, 1), date(2023, 1, 31))
        assert len(result["AAPL"]) == 1

    def test_raises_after_max_retries(self, provider):
        responses = [_mock_429()] * 5
        with patch("requests.get", side_effect=responses), \
             patch("time.sleep"):
            with pytest.raises(RuntimeError, match="max retries exceeded"):
                provider.get_bars(["AAPL"], date(2023, 1, 1), date(2023, 1, 31))

    def test_single_429_triggers_sleep(self, provider):
        responses = [_mock_429(), _mock_response(_aggs_response())]
        with patch("requests.get", side_effect=responses), \
             patch("time.sleep") as mock_sleep:
            provider.get_bars(["AAPL"], date(2023, 1, 1), date(2023, 1, 31))
        mock_sleep.assert_called_once_with(1)  # 2^0 = 1


# ---------------------------------------------------------------------------
# API error in body
# ---------------------------------------------------------------------------

class TestAPIError:
    def test_raises_on_error_status_in_body(self, provider):
        resp = _mock_response({"status": "ERROR", "error": "Not authorized"})
        with patch("requests.get", return_value=resp):
            with pytest.raises(RuntimeError, match="Massive API error"):
                provider.get_bars(["AAPL"], date(2023, 1, 1), date(2023, 1, 31))


# ---------------------------------------------------------------------------
# get_snapshot
# ---------------------------------------------------------------------------

class TestGetSnapshot:
    def test_returns_bar_for_each_ticker(self, provider):
        snap_body = {
            "status": "OK",
            "tickers": [
                {
                    "ticker": "AAPL",
                    "day": {"o": 185.0, "h": 188.5, "l": 184.0, "c": 187.0, "v": 60_000_000, "vw": 186.3},
                    "updated": 1_703_880_601_000_000_000,
                }
            ],
        }
        resp = _mock_response(snap_body)
        with patch("requests.get", return_value=resp):
            result = provider.get_snapshot(["AAPL"])
        assert "AAPL" in result
        bar = result["AAPL"]
        assert bar.ticker == "AAPL"
        assert bar.close == pytest.approx(187.0)

    def test_falls_back_to_prevday(self, provider):
        snap_body = {
            "status": "OK",
            "tickers": [
                {
                    "ticker": "MSFT",
                    "day": {},
                    "prevDay": {"o": 370.0, "h": 375.0, "l": 368.0, "c": 373.0, "v": 20_000_000, "vw": 372.5},
                    "updated": 1_703_880_601_000_000_000,
                }
            ],
        }
        resp = _mock_response(snap_body)
        with patch("requests.get", return_value=resp):
            result = provider.get_snapshot(["MSFT"])
        assert result["MSFT"].close == pytest.approx(373.0)

    def test_empty_tickers_returns_empty_dict(self, provider):
        snap_body = {"status": "OK", "tickers": []}
        resp = _mock_response(snap_body)
        with patch("requests.get", return_value=resp):
            result = provider.get_snapshot([])
        assert result == {}


# ---------------------------------------------------------------------------
# get_latest_quote
# ---------------------------------------------------------------------------

class TestGetLatestQuote:
    def test_returns_quote_for_ticker(self, provider):
        snap_body = {
            "status": "OK",
            "tickers": [
                {
                    "ticker": "AAPL",
                    "lastQuote": {"P": 187.05, "S": 100},
                    "updated": 1_703_880_601_000_000_000,
                }
            ],
        }
        resp = _mock_response(snap_body)
        with patch("requests.get", return_value=resp):
            result = provider.get_latest_quote(["AAPL"])
        q = result["AAPL"]
        assert q.ticker == "AAPL"
        assert q.bid == pytest.approx(187.05)
        assert q.ask == pytest.approx(187.05)

    def test_starter_plan_no_lastquote(self, provider):
        snap_body = {
            "status": "OK",
            "tickers": [
                {
                    "ticker": "AAPL",
                    # No lastQuote key — Starter plan
                    "updated": 1_703_880_601_000_000_000,
                }
            ],
        }
        resp = _mock_response(snap_body)
        with patch("requests.get", return_value=resp):
            result = provider.get_latest_quote(["AAPL"])
        # Defaults to 0.0 when lastQuote is absent
        q = result["AAPL"]
        assert q.bid == pytest.approx(0.0)
        assert q.ask == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# get_daily_market_summary
# ---------------------------------------------------------------------------

class TestGetDailyMarketSummary:
    def test_returns_bars_keyed_by_ticker(self, provider):
        body = {
            "status": "OK",
            "results": [
                {"T": "AAPL", "o": 150.0, "h": 155.0, "l": 149.0, "c": 153.5, "v": 82_000_000, "vw": 152.7},
                {"T": "MSFT", "o": 370.0, "h": 375.0, "l": 368.0, "c": 373.0, "v": 20_000_000, "vw": 372.5},
            ],
        }
        resp = _mock_response(body)
        with patch("requests.get", return_value=resp):
            result = provider.get_daily_market_summary(date(2023, 6, 15))
        assert "AAPL" in result
        assert "MSFT" in result
        assert result["AAPL"].close == pytest.approx(153.5)
        assert result["AAPL"].date == date(2023, 6, 15)

    def test_skips_entries_without_ticker(self, provider):
        body = {
            "status": "OK",
            "results": [
                {"o": 150.0, "h": 155.0, "l": 149.0, "c": 153.5, "v": 100},  # missing "T"
                {"T": "MSFT", "o": 370.0, "h": 375.0, "l": 368.0, "c": 373.0, "v": 20_000_000},
            ],
        }
        resp = _mock_response(body)
        with patch("requests.get", return_value=resp):
            result = provider.get_daily_market_summary(date(2023, 6, 15))
        assert "MSFT" in result
        assert len(result) == 1

    def test_empty_results(self, provider):
        resp = _mock_response({"status": "OK", "results": []})
        with patch("requests.get", return_value=resp):
            result = provider.get_daily_market_summary(date(2023, 6, 15))
        assert result == {}


# ---------------------------------------------------------------------------
# Timestamp conversion
# ---------------------------------------------------------------------------

class TestTimestampConversion:
    def test_ms_to_et_datetime(self, provider):
        # 1672531200000 ms = 2023-01-01 00:00:00 UTC = 2022-12-31 19:00:00 ET
        # After normalize() this becomes 2022-12-31 in ET
        bar = _bar_result(t_ms=1672531200000)
        resp = _mock_response(_aggs_response(bars=[bar]))
        with patch("requests.get", return_value=resp):
            result = provider.get_bars(["AAPL"], date(2022, 12, 1), date(2023, 1, 31))
        df = result["AAPL"]
        assert len(df) == 1
        # After tz_convert("America/New_York").normalize(), time is midnight ET
        assert df.iloc[0]["date"].time().hour == 0
        assert df.iloc[0]["date"].time().minute == 0

    def test_date_column_tz_is_et(self, provider):
        resp = _mock_response(_aggs_response())
        with patch("requests.get", return_value=resp):
            result = provider.get_bars(["AAPL"], date(2023, 1, 1), date(2023, 1, 31))
        tz = result["AAPL"]["date"].dt.tz
        assert tz is not None
        assert "New_York" in str(tz)


# ---------------------------------------------------------------------------
# Constructor / auth
# ---------------------------------------------------------------------------

class TestAuth:
    def test_requires_api_key_from_env(self, monkeypatch):
        monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
        with pytest.raises(KeyError):
            MassiveProvider()  # no api_key arg, env var absent

    def test_accepts_injected_api_key(self):
        p = MassiveProvider(api_key="my_key")
        assert p._key == "my_key"

    def test_base_url_override(self, monkeypatch):
        monkeypatch.setenv("MASSIVE_BASE_URL", "https://custom.proxy.example.com")
        p = MassiveProvider(api_key="k")
        assert p._base == "https://custom.proxy.example.com"

    def test_default_base_url(self, monkeypatch):
        monkeypatch.delenv("MASSIVE_BASE_URL", raising=False)
        p = MassiveProvider(api_key="k")
        assert "polygon.io" in p._base
