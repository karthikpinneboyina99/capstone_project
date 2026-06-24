"""
MassiveProvider — live market data via the Massive (formerly Polygon.io) REST API.

Requires MASSIVE_API_KEY in the environment. All HTTP calls go through _get(),
which applies exponential backoff on 429 responses and raises on API errors.

Endpoint reference: planning/MASSIVE_API.md
"""
from __future__ import annotations

import os
import time
from datetime import date

import pandas as pd
import requests

from .market_interface import Bar, MarketDataProvider, Quote

_DEFAULT_BASE = "https://api.polygon.io"


class MassiveProvider(MarketDataProvider):
    """Live market data from the Massive/Polygon REST API."""

    def __init__(self, api_key: str | None = None) -> None:
        self._key = api_key or os.environ["MASSIVE_API_KEY"]
        self._base = os.environ.get("MASSIVE_BASE_URL", _DEFAULT_BASE).rstrip("/")

    # ------------------------------------------------------------------
    # MarketDataProvider interface
    # ------------------------------------------------------------------

    def get_bars(
        self,
        tickers: list[str],
        from_date: date,
        to_date: date,
        timespan: str = "day",
    ) -> dict[str, pd.DataFrame]:
        results: dict[str, pd.DataFrame] = {}
        for ticker in tickers:
            raw = self._fetch_aggs(ticker, from_date, to_date, timespan)
            results[ticker] = self._to_df(ticker, raw)
        return results

    def get_latest_quote(self, tickers: list[str]) -> dict[str, Quote]:
        snaps = self._get_snapshots(tickers)
        out: dict[str, Quote] = {}
        for ticker, snap in snaps.items():
            lt = snap.get("lastQuote") or {}
            # Fall back to last trade price so bid/ask are never 0.0 on Starter plan
            last_trade_price = (snap.get("lastTrade") or {}).get("p", 0.0)
            bid_ask = lt.get("P", last_trade_price)
            out[ticker] = Quote(
                ticker=ticker,
                bid=bid_ask,
                ask=bid_ask,
                bid_size=lt.get("S", 0),
                ask_size=lt.get("S", 0),
                timestamp=pd.Timestamp(snap.get("updated", 0), unit="ns", tz="UTC"),
            )
        return out

    def get_snapshot(self, tickers: list[str]) -> dict[str, Bar]:
        snaps = self._get_snapshots(tickers)
        out: dict[str, Bar] = {}
        for ticker, snap in snaps.items():
            day = snap.get("day") or snap.get("prevDay") or {}
            updated_ns = snap.get("updated", 0)
            bar_date = (
                pd.Timestamp(updated_ns, unit="ns", tz="UTC")
                .tz_convert("America/New_York")
                .date()
                if updated_ns
                else date.today()
            )
            out[ticker] = Bar(
                ticker=ticker,
                date=bar_date,
                open=day.get("o", 0.0),
                high=day.get("h", 0.0),
                low=day.get("l", 0.0),
                close=day.get("c", 0.0),
                volume=int(day.get("v", 0)),
                vwap=day.get("vw"),
            )
        return out

    def get_daily_market_summary(self, as_of: date) -> dict[str, Bar]:
        url = f"{self._base}/v2/aggs/grouped/locale/global/market/stocks/{as_of}"
        raw = self._get(url, {"adjusted": "true"})
        out: dict[str, Bar] = {}
        for item in raw.get("results") or []:
            t = item.get("T", "")
            if not t:
                continue
            out[t] = Bar(
                ticker=t,
                date=as_of,
                open=item["o"],
                high=item["h"],
                low=item["l"],
                close=item["c"],
                volume=int(item["v"]),
                vwap=item.get("vw"),
            )
        return out

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_aggs(
        self,
        ticker: str,
        from_date: date,
        to_date: date,
        timespan: str,
    ) -> list[dict]:
        url = (
            f"{self._base}/v2/aggs/ticker/{ticker}"
            f"/range/1/{timespan}/{from_date}/{to_date}"
        )
        params: dict = {"adjusted": "true", "sort": "asc", "limit": 50000}
        results: list[dict] = []
        while url:
            body = self._get(url, params)
            results.extend(body.get("results") or [])
            url = body.get("next_url", "")
            params = {}  # next_url is self-contained; only apiKey needed
        return results

    def _get_snapshots(self, tickers: list[str]) -> dict[str, dict]:
        url = f"{self._base}/v2/snapshot/locale/us/markets/stocks/tickers"
        body = self._get(url, {"tickers": ",".join(tickers)})
        return {item["ticker"]: item for item in (body.get("tickers") or [])}

    _RETRY_ON = {429, 500, 502, 503, 504}

    def _get(self, url: str, params: dict) -> dict:
        """GET with retry on 429 and transient 5xx. Raises on non-recoverable errors."""
        # Don't append apiKey when it is already embedded in the URL (next_url pagination).
        full_params = {**params}
        if "apiKey" not in url:
            full_params["apiKey"] = self._key
        for attempt in range(5):
            response = requests.get(url, params=full_params, timeout=15)
            if response.status_code in self._RETRY_ON:
                time.sleep(2 ** attempt)
                continue
            response.raise_for_status()
            body = response.json()
            if body.get("status") == "ERROR":
                raise RuntimeError(
                    f"Massive API error: {body.get('error', 'unknown')}"
                )
            return body
        raise RuntimeError("Massive API rate limit: max retries exceeded")

    @staticmethod
    def _to_df(ticker: str, raw: list[dict]) -> pd.DataFrame:
        """Convert raw Polygon agg results to a normalised OHLCV DataFrame."""
        if not raw:
            return pd.DataFrame(
                columns=["date", "open", "high", "low", "close", "volume", "vwap"]
            )
        df = pd.DataFrame(raw)
        df["date"] = (
            pd.to_datetime(df["t"], unit="ms", utc=True)
            .dt.tz_convert("America/New_York")
            .dt.normalize()
        )
        df = df.rename(
            columns={
                "o": "open",
                "h": "high",
                "l": "low",
                "c": "close",
                "v": "volume",
                "vw": "vwap",
            }
        )
        cols = ["date", "open", "high", "low", "close", "volume", "vwap"]
        for col in cols:
            if col not in df.columns:
                df[col] = None
        return df[cols].reset_index(drop=True)
