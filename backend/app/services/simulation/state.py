"""
Shared in-memory simulation state.
Prices are updated by the /stream/prices SSE generator (which already runs SimulatorProvider).
The simulation endpoints read from here for fills.
"""
from __future__ import annotations
import threading
from datetime import datetime, timezone

# Latest prices from the SimulatorProvider tick loop
# Updated by stream.py's generate() loop via update_prices()
_lock = threading.Lock()
_prices: dict[str, float] = {}
_last_updated: datetime | None = None


def update_prices(prices: dict[str, float]) -> None:
    with _lock:
        _prices.update(prices)
        global _last_updated
        _last_updated = datetime.now(tz=timezone.utc)


def get_price(symbol: str) -> float | None:
    with _lock:
        return _prices.get(symbol)


def get_all_prices() -> dict[str, float]:
    with _lock:
        return dict(_prices)


def get_last_updated() -> datetime | None:
    with _lock:
        return _last_updated
