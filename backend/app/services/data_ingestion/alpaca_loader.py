"""
Live daily bar ingestion via Alpaca Market Data API (paper account).
Used by the daily job to pull the most recent trading day's bars
after market close, before running signals.
"""
import logging
from datetime import date, timedelta, timezone

from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.models import Instrument, PriceBar

logger = logging.getLogger(__name__)

TIMEFRAME = "1d"


def _get_or_create_instrument(db: Session, symbol: str) -> Instrument:
    inst = db.query(Instrument).filter_by(symbol=symbol).first()
    if inst is None:
        inst = Instrument(symbol=symbol, asset_class="equity", is_active=True)
        db.add(inst)
        db.flush()
    return inst


def fetch_latest_bars(
    db: Session,
    symbols: list[str],
    lookback_days: int = 5,
) -> dict[str, int]:
    """
    Pull the last `lookback_days` of daily bars for each symbol from Alpaca
    and upsert into price_bars.
    Returns dict mapping symbol -> rows upserted (or -1 on error).
    """
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
    except ImportError:
        logger.error("alpaca-py not installed; skipping Alpaca loader")
        return {s: 0 for s in symbols}

    client = StockHistoricalDataClient(
        api_key=settings.ALPACA_API_KEY or None,
        secret_key=settings.ALPACA_SECRET_KEY or None,
    )

    start_date = date.today() - timedelta(days=lookback_days + 3)  # buffer for weekends

    upserted: dict[str, int] = {}

    for symbol in symbols:
        try:
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Day,
                start=start_date.isoformat(),
                end=date.today().isoformat(),
                adjustment="all",  # split + dividend adjusted
            )
            bars_resp = client.get_stock_bars(request)
            bars = bars_resp.get(symbol, [])

            if not bars:
                logger.warning("Alpaca returned no bars for %s", symbol)
                upserted[symbol] = 0
                continue

            inst = _get_or_create_instrument(db, symbol)

            rows = []
            for bar in bars:
                ts = bar.timestamp
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                rows.append({
                    "instrument_id": inst.id,
                    "timestamp": ts,
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": float(bar.close),
                    "volume": int(bar.volume),
                    "timeframe": TIMEFRAME,
                })

            if rows:
                stmt = pg_insert(PriceBar.__table__).values(rows)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_price_bar",
                    set_={
                        "open": stmt.excluded.open,
                        "high": stmt.excluded.high,
                        "low": stmt.excluded.low,
                        "close": stmt.excluded.close,
                        "volume": stmt.excluded.volume,
                    },
                )
                db.execute(stmt)

            db.commit()
            upserted[symbol] = len(rows)
            logger.info("Alpaca: upserted %d bars for %s", len(rows), symbol)

        except Exception:
            db.rollback()
            logger.exception("Failed to ingest %s from Alpaca", symbol)
            upserted[symbol] = -1

    return upserted
