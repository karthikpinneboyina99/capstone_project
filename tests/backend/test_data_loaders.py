"""
Unit tests for data ingestion loaders.
All external calls (yfinance, Alpaca, NewsAPI) are mocked.
"""
import pytest
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch
import pandas as pd


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_db():
    """Minimal mock that satisfies the loader interface."""
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = None
    return db


# ── yfinance loader ──────────────────────────────────────────────────────────

class TestYfinanceLoader:
    def _sample_df(self):
        idx = pd.DatetimeIndex(
            [
                datetime(2024, 1, 2, tzinfo=timezone.utc),
                datetime(2024, 1, 3, tzinfo=timezone.utc),
            ]
        )
        return pd.DataFrame(
            {
                "Open": [100.0, 101.0],
                "High": [105.0, 106.0],
                "Low": [99.0, 100.0],
                "Close": [104.0, 105.0],
                "Volume": [1_000_000, 1_100_000],
            },
            index=idx,
        )

    def test_returns_row_count_per_symbol(self):
        from app.services.data_ingestion import yfinance_loader

        with patch("app.services.data_ingestion.yfinance_loader.yf") as mock_yf:
            ticker_mock = MagicMock()
            ticker_mock.history.return_value = self._sample_df()
            mock_yf.Ticker.return_value = ticker_mock

            db = _make_db()
            inst_mock = MagicMock(id=1)
            db.query.return_value.filter_by.return_value.first.return_value = inst_mock

            result = yfinance_loader.fetch_and_store(db, ["AAPL"])

        assert result["AAPL"] == 2

    def test_empty_response_returns_zero(self):
        from app.services.data_ingestion import yfinance_loader

        with patch("app.services.data_ingestion.yfinance_loader.yf") as mock_yf:
            ticker_mock = MagicMock()
            ticker_mock.history.return_value = pd.DataFrame()
            mock_yf.Ticker.return_value = ticker_mock

            db = _make_db()
            result = yfinance_loader.fetch_and_store(db, ["UNKNOWN"])

        assert result["UNKNOWN"] == 0

    def test_exception_returns_minus_one(self):
        from app.services.data_ingestion import yfinance_loader

        with patch("app.services.data_ingestion.yfinance_loader.yf") as mock_yf:
            mock_yf.Ticker.side_effect = RuntimeError("network error")

            db = _make_db()
            result = yfinance_loader.fetch_and_store(db, ["ERR"])

        assert result["ERR"] == -1


# ── news loader ───────────────────────────────────────────────────────────────

class TestNewsLoader:
    def test_no_api_key_returns_zero(self, monkeypatch):
        from app.services.data_ingestion import news_loader
        monkeypatch.setattr(news_loader.settings, "NEWS_API_KEY", "")

        db = _make_db()
        result = news_loader.fetch_and_store(db, ["AAPL"])

        assert result["AAPL"] == 0

    def test_stores_articles(self, monkeypatch):
        from app.services.data_ingestion import news_loader
        monkeypatch.setattr(news_loader.settings, "NEWS_API_KEY", "test_key")

        fake_articles = [
            {
                "title": "AAPL hits record",
                "description": "Apple stock surges",
                "source": {"name": "Reuters"},
                "url": "https://example.com/1",
                "publishedAt": "2024-01-02T10:00:00Z",
            }
        ]

        with patch("app.services.data_ingestion.news_loader.requests.get") as mock_get:
            mock_get.return_value.json.return_value = {"articles": fake_articles}
            mock_get.return_value.raise_for_status = MagicMock()

            db = _make_db()
            inst_mock = MagicMock(id=1)
            db.query.return_value.filter_by.return_value.first.return_value = inst_mock

            result = news_loader.fetch_and_store(db, ["AAPL"], as_of=date(2024, 1, 2))

        assert result["AAPL"] == 1

    def test_uses_as_of_date_as_upper_bound(self, monkeypatch):
        """The `to` param must equal as_of so backtester sees no future news."""
        from app.services.data_ingestion import news_loader
        monkeypatch.setattr(news_loader.settings, "NEWS_API_KEY", "test_key")

        captured_params = {}

        def fake_get(url, params=None, timeout=None):
            captured_params.update(params or {})
            resp = MagicMock()
            resp.json.return_value = {"articles": []}
            resp.raise_for_status = MagicMock()
            return resp

        with patch("app.services.data_ingestion.news_loader.requests.get", fake_get):
            db = _make_db()
            news_loader.fetch_and_store(db, ["MSFT"], as_of=date(2024, 6, 1))

        assert captured_params["to"] == "2024-06-01"
