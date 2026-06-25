"""
News headline ingestion via NewsAPI (free tier: 100 req/day).
Pulls the latest 5 headlines per symbol and upserts into news_articles.
Filters by published_at <= as_of_date to prevent lookahead in backtesting.
"""
import logging
from datetime import date, timedelta, timezone
from datetime import datetime

import requests
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Instrument, NewsArticle

logger = logging.getLogger(__name__)

_NEWSAPI_URL = "https://newsapi.org/v2/everything"


def _get_or_create_instrument(db: Session, symbol: str) -> Instrument:
    inst = db.query(Instrument).filter_by(symbol=symbol).first()
    if inst is None:
        inst = Instrument(symbol=symbol, asset_class="equity", is_active=True)
        db.add(inst)
        db.flush()
    return inst


def fetch_and_store(
    db: Session,
    symbols: list[str],
    as_of: date | None = None,
    page_size: int = 5,
) -> dict[str, int]:
    """
    Fetch up to `page_size` recent headlines per symbol from NewsAPI.

    IMPORTANT: uses `to=as_of_date` in the API request so the backtester
    never receives articles published after the historical date being processed.
    Returns dict mapping symbol -> rows stored (or -1 on error).
    """
    if not settings.NEWS_API_KEY:
        logger.warning("NEWS_API_KEY not set; skipping news ingestion")
        return {s: 0 for s in symbols}

    if as_of is None:
        as_of = date.today()

    stored: dict[str, int] = {}

    for symbol in symbols:
        try:
            resp = requests.get(
                _NEWSAPI_URL,
                params={
                    "q": symbol,
                    "from": (as_of - timedelta(days=7)).isoformat(),
                    "to": as_of.isoformat(),
                    "sortBy": "publishedAt",
                    "pageSize": page_size,
                    "language": "en",
                    "apiKey": settings.NEWS_API_KEY,
                },
                timeout=10,
            )
            resp.raise_for_status()
            articles = resp.json().get("articles", [])

            if not articles:
                stored[symbol] = 0
                continue

            inst = _get_or_create_instrument(db, symbol)

            rows = []
            for art in articles:
                pub_str = art.get("publishedAt", "")
                try:
                    pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                except ValueError:
                    pub_dt = datetime.now(tz=timezone.utc)

                rows.append({
                    "instrument_id": inst.id,
                    "published_at": pub_dt,
                    "headline": (art.get("title") or "")[:512],
                    "summary": art.get("description") or None,
                    "source": (art.get("source") or {}).get("name") or None,
                    "url": (art.get("url") or "")[:1024] or None,
                    "sentiment_score": None,  # populated later if needed
                })

            if rows:
                stmt = pg_insert(NewsArticle.__table__).values(rows)
                # No unique constraint on articles — insert ignore duplicates by url
                stmt = stmt.on_conflict_do_nothing()
                db.execute(stmt)

            db.commit()
            stored[symbol] = len(rows)
            logger.info("NewsAPI: stored %d articles for %s", len(rows), symbol)

        except Exception:
            db.rollback()
            logger.exception("Failed to fetch news for %s", symbol)
            stored[symbol] = -1

    return stored
