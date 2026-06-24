# Massive API Reference (formerly Polygon.io)

Polygon.io rebranded to **Massive** in 2025. The domain `polygon.io` now permanently redirects (HTTP 301) to `massive.com`. The REST API surface and authentication scheme are unchanged — only the base hostname moved.

- Marketing/docs site: `https://massive.com`
- REST base URL: `https://api.polygon.io` (legacy, still works) / `https://api.massive.com` (canonical new form)
- WebSocket base URL: `wss://socket.polygon.io` / `wss://socket.massive.com`
- Official Python client: `polygon-api-client` (PyPI); plain `requests` or `httpx` work fine too

---

## Authentication

Every request requires your API key. Pass it as a query parameter or as a Bearer token header:

```python
# Query-param style (simplest)
GET https://api.polygon.io/v2/aggs/ticker/AAPL/range/1/day/2024-01-01/2024-12-31?apiKey=YOUR_KEY

# Header style
Authorization: Bearer YOUR_KEY
```

The env var used in this project is `MASSIVE_API_KEY` (see `.env.example`).

---

## Plans & Rate Limits

| Plan | Aggs | Quotes/Trades | History | Rate limit |
|------|------|---------------|---------|-----------|
| Stocks Starter | Day + minute bars (EOD) | No | 5 years | ~5 req/min |
| Stocks Advanced | All aggs (real-time) | Yes | Full (since 2003) | Higher |
| Business | All + Fair Market Value | Yes | Full | Highest |

The Starter plan is sufficient for this project (daily OHLCV + EOD snapshots for the watchlist).

---

## REST Endpoints

### 1. Aggregate Bars (OHLCV) — primary historical data source

```
GET /v2/aggs/ticker/{stockTicker}/range/{multiplier}/{timespan}/{from}/{to}
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `stockTicker` | path | Ticker symbol, e.g. `AAPL` |
| `multiplier` | path | Timeframe size integer, e.g. `1` |
| `timespan` | path | `minute`, `hour`, `day`, `week`, `month`, `quarter`, `year` |
| `from` | path | Start date `YYYY-MM-DD` or Unix ms timestamp |
| `to` | path | End date `YYYY-MM-DD` or Unix ms timestamp |
| `adjusted` | query | `true` (default) — adjusts for splits & dividends |
| `sort` | query | `asc` (default) or `desc` |
| `limit` | query | Max bars per response (default 5000, max 50000) |

```python
import os, requests

BASE = "https://api.polygon.io"
KEY  = os.environ["MASSIVE_API_KEY"]

def get_bars(ticker: str, from_date: str, to_date: str, timespan: str = "day") -> list[dict]:
    url = f"{BASE}/v2/aggs/ticker/{ticker}/range/1/{timespan}/{from_date}/{to_date}"
    params = {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": KEY}
    results = []
    while url:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        results.extend(data.get("results") or [])
        url = data.get("next_url")       # pagination cursor
        params = {"apiKey": KEY}         # next_url already has other params baked in
    return results

# Example: 2 years of daily bars for AAPL
bars = get_bars("AAPL", "2023-01-01", "2024-12-31")
# Each bar: {"o": 150.0, "h": 155.0, "l": 149.0, "c": 153.5,
#            "v": 82000000, "vw": 152.7, "t": 1672531200000, "n": 45000}
# t = Unix millisecond timestamp (UTC)
```

**Response schema:**

```json
{
  "status": "OK",
  "ticker": "AAPL",
  "resultsCount": 252,
  "adjusted": true,
  "results": [
    {
      "o":  150.23,
      "h":  155.10,
      "l":  149.88,
      "c":  153.50,
      "v":  82345678,
      "vw": 152.74,
      "t":  1672531200000,
      "n":  44821
    }
  ],
  "next_url": "https://api.polygon.io/v2/aggs/...?cursor=abc123"
}
```

`o/h/l/c` are adjusted prices when `adjusted=true`.

---

### 2. Daily Market Summary — all tickers on a date

```
GET /v2/aggs/grouped/locale/global/market/stocks/{date}
```

Returns OHLCV for **every** US equity in a single call. Useful for bulk EOD ingestion.

```python
def get_daily_market_summary(date: str) -> list[dict]:
    url = f"{BASE}/v2/aggs/grouped/locale/global/market/stocks/{date}"
    r = requests.get(url, params={"adjusted": "true", "apiKey": KEY}, timeout=30)
    r.raise_for_status()
    return r.json().get("results") or []

# Returns same bar schema as /v2/aggs, but with an added "T" field for ticker:
# {"T": "AAPL", "o": 150.0, "h": 155.0, "l": 149.0, "c": 153.5, "v": 82000000, ...}
```

---

### 3. Previous Day Bar — single ticker

```
GET /v2/aggs/ticker/{stockTicker}/prev
```

```python
def get_prev_day(ticker: str) -> dict:
    r = requests.get(f"{BASE}/v2/aggs/ticker/{ticker}/prev",
                     params={"adjusted": "true", "apiKey": KEY}, timeout=10)
    r.raise_for_status()
    results = r.json().get("results") or []
    return results[0] if results else {}
```

---

### 4. Snapshot — multiple tickers (real-time, requires Advanced plan)

```
GET /v2/snapshot/locale/us/markets/stocks/tickers
```

Omit `tickers` to get the full market; pass a comma-separated list to filter.

```python
def get_snapshots(tickers: list[str]) -> dict[str, dict]:
    params = {
        "tickers": ",".join(tickers),
        "apiKey": KEY,
    }
    r = requests.get(f"{BASE}/v2/snapshot/locale/us/markets/stocks/tickers",
                     params=params, timeout=15)
    r.raise_for_status()
    raw = r.json().get("tickers") or []
    return {item["ticker"]: item for item in raw}

snapshots = get_snapshots(["AAPL", "MSFT", "NVDA"])
# snapshots["AAPL"] contains:
# {
#   "ticker": "AAPL",
#   "day":    {"o": 185.0, "h": 188.5, "l": 184.2, "c": 187.0, "v": 60000000, "vw": 186.3},
#   "min":    {"o": 186.8, "h": 187.1, "l": 186.5, "c": 186.9, "v": 450000, "vw": 186.8},
#   "prevDay":{"o": 183.0, "h": 186.0, "l": 182.5, "c": 185.5, "v": 55000000},
#   "lastTrade": {"p": 187.0, "s": 100, "t": 1703880600000000000},
#   "todaysChangePerc": 0.81,
#   "todaysChange": 1.50,
#   "updated": 1703880601000000000
# }
```

---

### 5. Single Ticker Snapshot

```
GET /v2/snapshot/locale/us/markets/stocks/tickers/{ticker}
```

```python
def get_snapshot(ticker: str) -> dict:
    r = requests.get(f"{BASE}/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}",
                     params={"apiKey": KEY}, timeout=10)
    r.raise_for_status()
    return r.json().get("ticker") or {}
```

---

### 6. Daily Open-Close

```
GET /v1/open-close/{stockTicker}/{date}
```

```python
def get_open_close(ticker: str, date: str) -> dict:
    r = requests.get(f"{BASE}/v1/open-close/{ticker}/{date}",
                     params={"adjusted": "true", "apiKey": KEY}, timeout=10)
    r.raise_for_status()
    return r.json()
# {"status": "OK", "symbol": "AAPL", "open": 150.0, "close": 153.5,
#  "high": 155.0, "low": 149.0, "volume": 82000000, "afterHours": 153.0, ...}
```

---

### 7. Top Market Movers

```
GET /v2/snapshot/locale/us/markets/stocks/{direction}
```

`direction` is `gainers` or `losers`. Returns the top 20 by percentage change.

```python
def get_top_movers(direction: str = "gainers") -> list[dict]:
    r = requests.get(f"{BASE}/v2/snapshot/locale/us/markets/stocks/{direction}",
                     params={"apiKey": KEY}, timeout=10)
    r.raise_for_status()
    return r.json().get("tickers") or []
```

---

## Pagination

Responses may include a `next_url` field. Always follow it until absent to retrieve all results:

```python
def paginate(initial_url: str, params: dict) -> list[dict]:
    results, url = [], initial_url
    while url:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        body = r.json()
        results.extend(body.get("results") or [])
        url = body.get("next_url")
        params = {"apiKey": KEY}   # next_url is self-contained; only re-add apiKey
    return results
```

---

## WebSocket Streaming (Advanced plan)

Connect to `wss://socket.polygon.io/stocks`, authenticate, then subscribe:

```python
import asyncio, json
import websockets

WS_URL = "wss://socket.polygon.io/stocks"

async def stream_quotes(tickers: list[str], on_message):
    async with websockets.connect(WS_URL) as ws:
        # Server sends {"ev":"status","status":"connected"} immediately
        await ws.recv()

        # Authenticate
        await ws.send(json.dumps({"action": "auth", "params": KEY}))
        auth_resp = json.loads(await ws.recv())
        assert auth_resp[0]["status"] == "auth_success", f"Auth failed: {auth_resp}"

        # Subscribe: prefix determines feed type
        # Q.* = quotes, T.* = trades, AM.* = per-minute aggs, A.* = per-second aggs
        subs = ",".join(f"AM.{t}" for t in tickers)   # per-minute OHLCV
        await ws.send(json.dumps({"action": "subscribe", "params": subs}))

        async for raw in ws:
            for msg in json.loads(raw):
                await on_message(msg)
```

**Per-minute aggregate message schema (`ev: "AM"`):**

```json
{
  "ev": "AM",
  "sym": "AAPL",
  "o":   186.50,
  "h":   186.90,
  "l":   186.40,
  "c":   186.75,
  "v":   42500,
  "vw":  186.63,
  "s":   1703880600000,
  "e":   1703880660000,
  "av":  12450000,
  "op":  185.00,
  "a":   186.20
}
```

`s`/`e` = interval start/end as Unix ms; `av` = accumulated daily volume; `op` = official opening price; `a` = VWAP from day open.

---

## Official Python Client

```python
pip install polygon-api-client
```

```python
from polygon import RESTClient
import os

client = RESTClient(api_key=os.environ["MASSIVE_API_KEY"])

# Aggregate bars
bars = list(client.list_aggs("AAPL", 1, "day", "2024-01-01", "2024-12-31", adjusted=True))

# Snapshot for multiple tickers
snaps = client.get_snapshot_all("stocks", tickers=["AAPL", "MSFT", "NVDA"])
```

The official client handles pagination and auth automatically. Use it in production; use raw `requests` in tests (easier to mock).

---

## Timestamp Handling

All REST timestamps are **Unix milliseconds UTC**. Convert for pandas/Python:

```python
import pandas as pd

df = pd.DataFrame(bars)
df["date"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.tz_convert("America/New_York")
```

WebSocket timestamps use **Unix nanoseconds**; divide by 1e9 to get seconds.

---

## Error Codes

| HTTP | Meaning |
|------|---------|
| 200 | OK (check `status` field in body — can be `"ERROR"` even on 200) |
| 400 | Bad request / invalid parameters |
| 403 | Invalid API key |
| 429 | Rate limit exceeded; back off and retry |

Always check `r.json()["status"] == "OK"` even after a 200.
