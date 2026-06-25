"""
Historical daily bar ingestion via yfinance.

Uses auto_adjust=True so all prices are split- and dividend-adjusted.
Upserts into price_bars using ON CONFLICT DO UPDATE so re-runs are idempotent.
"""
import logging
from datetime import date, datetime, timezone

import pandas as pd
import yfinance as yf
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import Instrument, PriceBar

logger = logging.getLogger(__name__)

TIMEFRAME = "1d"


def _get_or_create_instrument(db: Session, symbol: str) -> Instrument:
    inst = db.query(Instrument).filter_by(symbol=symbol).first()
    if inst is None:
        inst = Instrument(symbol=symbol, asset_class="equity", is_active=True)
        db.add(inst)
        db.flush()  # get the id without committing
    return inst


def fetch_and_store(
    db: Session,
    symbols: list[str],
    start: date | None = None,
    end: date | None = None,
) -> dict[str, int]:
    """
    Download daily bars for each symbol and upsert into price_bars.

    Returns a dict mapping symbol -> number of rows upserted.
    If start is None, defaults to 5 years ago. If end is None, defaults to today.
    """
    from datetime import timedelta

    if start is None:
        start = date.today() - timedelta(days=365 * 5)
    if end is None:
        end = date.today()

    upserted: dict[str, int] = {}

    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            df: pd.DataFrame = ticker.history(
                start=start.isoformat(),
                end=end.isoformat(),
                interval="1d",
                auto_adjust=True,
                actions=False,
            )
            if df.empty:
                logger.warning("yfinance returned no data for %s", symbol)
                upserted[symbol] = 0
                continue

            inst = _get_or_create_instrument(db, symbol)

            rows = []
            for ts, row in df.iterrows():
                # yfinance index is timezone-aware; normalise to UTC
                if hasattr(ts, "tzinfo") and ts.tzinfo is not None:
                    ts_utc = ts.to_pydatetime()
                else:
                    ts_utc = ts.to_pydatetime().replace(tzinfo=timezone.utc)

                rows.append({
                    "instrument_id": inst.id,
                    "timestamp": ts_utc,
                    "open": float(row["Open"]) if pd.notna(row["Open"]) else None,
                    "high": float(row["High"]) if pd.notna(row["High"]) else None,
                    "low": float(row["Low"]) if pd.notna(row["Low"]) else None,
                    "close": float(row["Close"]) if pd.notna(row["Close"]) else None,
                    "volume": int(row["Volume"]) if pd.notna(row["Volume"]) else None,
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
            logger.info("yfinance: upserted %d bars for %s", len(rows), symbol)

        except Exception:
            db.rollback()
            logger.exception("Failed to ingest %s", symbol)
            upserted[symbol] = -1

    return upserted
