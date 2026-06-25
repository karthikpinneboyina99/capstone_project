"""
SSE streaming endpoint — sends portfolio updates and live price ticks to the frontend.
"""
import asyncio
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

# Allow importing SimulatorProvider from the project root
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

router = APIRouter()

WATCHLIST = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "SPY", "QQQ", "BRK.B"]
HISTORY_LEN = 18


async def _event_generator():
    while True:
        ts = datetime.now(tz=timezone.utc).isoformat()
        yield f"data: {{\"type\":\"heartbeat\",\"ts\":\"{ts}\"}}\n\n"
        await asyncio.sleep(15)


@router.get("/heartbeat", include_in_schema=False)
async def stream_heartbeat():
    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/prices")
async def stream_prices():
    """
    Stream live price ticks for the watchlist as Server-Sent Events.

    Each event is a JSON object::

        {
            "tick": 42,
            "ts": "14:35:22",
            "prices": {
                "AAPL": {"price": 185.42, "prev": 185.10, "volume": 1234567,
                         "bid": 185.40, "ask": 185.44, "history": [...]},
                ...
            }
        }

    Driven by SimulatorProvider (GBM offline simulation — no API key required).
    Updates approximately every 0.4 seconds.
    """

    async def generate():
        from app.services.data_ingestion.simulator_provider import SimulatorProvider

        provider = SimulatorProvider(db_session=None, seed=42)
        all_bars = provider.get_bars(WATCHLIST, date(2022, 1, 3), date(2024, 6, 28))
        frames = {t: df.to_dict("records") for t, df in all_bars.items()}
        n_frames = min(len(v) for v in frames.values())

        history: dict[str, list[float]] = {t: [] for t in WATCHLIST}

        # Seed history with the first HISTORY_LEN frames
        for i in range(min(HISTORY_LEN, n_frames)):
            for tkr in WATCHLIST:
                history[tkr].append(float(frames[tkr][i]["close"]))

        idx = HISTORY_LEN
        tick = 0
        prev_prices = {tkr: history[tkr][-1] if history[tkr] else 100.0 for tkr in WATCHLIST}

        while True:
            if idx >= n_frames:
                idx = HISTORY_LEN

            ts = time.strftime("%H:%M:%S")
            prices: dict[str, dict] = {}

            for tkr in WATCHLIST:
                row = frames[tkr][idx]
                px = float(row["close"])
                vol = int(row["volume"])
                bid = round(px * (1 - 0.0001), 2)
                ask = round(px * (1 + 0.0001), 2)

                history[tkr].append(px)
                if len(history[tkr]) > HISTORY_LEN:
                    history[tkr] = history[tkr][-HISTORY_LEN:]

                prices[tkr] = {
                    "price": px,
                    "prev": prev_prices.get(tkr, px),
                    "volume": vol,
                    "bid": bid,
                    "ask": ask,
                    "history": history[tkr][-HISTORY_LEN:],
                }
                prev_prices[tkr] = px

            tick += 1
            idx += 1

            # Update shared simulation state so simulation endpoints can use live prices
            try:
                from app.services.simulation.state import update_prices as _update_sim_prices
                _update_sim_prices({sym: d["price"] for sym, d in prices.items()})
            except Exception:
                pass

            payload = json.dumps({"tick": tick, "ts": ts, "prices": prices})
            yield f"data: {payload}\n\n"
            await asyncio.sleep(0.4)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
