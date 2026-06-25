import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.session import SessionLocal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ── Startup assertion: refuse to run against anything other than the paper endpoint ──
_PAPER_URL = "https://paper-api.alpaca.markets"
if settings.ALPACA_BASE_URL != _PAPER_URL:
    raise RuntimeError(
        f"ALPACA_BASE_URL is '{settings.ALPACA_BASE_URL}' — must be '{_PAPER_URL}'. "
        "This system only supports paper trading. Set the correct URL in .env and restart."
    )

app = FastAPI(
    title="AI Trading Workstation",
    description="Paper-trading platform with ML signals and LLM reasoning. NOT financial advice.",
    version="0.1.0",
)

# ── CORS ────────────────────────────────────────────────────────────────────────────
_origins = ["*"] if settings.ENVIRONMENT == "development" else [
    "https://your-frontend-domain.vercel.app",  # update before deploy
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routers ─────────────────────────────────────────────────────────────────────────
from app.api.routers import (
    instruments,
    prices,
    signals,
    decisions,
    trades,
    portfolio,
    backtests,
    stream,
    simulation,
)

app.include_router(instruments.router, prefix="/instruments", tags=["instruments"])
app.include_router(prices.router,      prefix="/prices",      tags=["prices"])
app.include_router(signals.router,     prefix="/signals",     tags=["signals"])
app.include_router(decisions.router,   prefix="/decisions",   tags=["decisions"])
app.include_router(trades.router,      prefix="/trades",      tags=["trades"])
app.include_router(portfolio.router,   prefix="/portfolio",   tags=["portfolio"])
app.include_router(backtests.router,   prefix="/backtests",   tags=["backtests"])
app.include_router(stream.router,      prefix="/stream",      tags=["stream"])
app.include_router(simulation.router,  prefix="/simulation",  tags=["simulation"])


@app.get("/health", tags=["health"])
def health() -> dict:
    return {
        "status": "ok",
        "mode": settings.TRADING_MODE,
        "environment": settings.ENVIRONMENT,
    }


# ── APScheduler: daily paper-trading job at 9:35 AM ET ──────────────────────────
def _run_daily_trading_job() -> None:
    """APScheduler callback — runs the paper-trading executor cycle."""
    from app.services.trading.executor import run_daily_cycle

    db = SessionLocal()
    try:
        result = run_daily_cycle(db)
        logger.info("Scheduled daily cycle result: %s", result)
    except Exception:
        logger.exception("Unhandled error in daily trading job")
    finally:
        db.close()


try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    _scheduler = BackgroundScheduler(timezone="America/New_York")
    _scheduler.add_job(
        _run_daily_trading_job,
        trigger=CronTrigger(hour=9, minute=35, day_of_week="mon-fri"),
        id="daily_paper_trade",
        replace_existing=True,
        misfire_grace_time=300,  # tolerate up to 5 min late start
    )
    _scheduler.start()
    logger.info("APScheduler started — daily paper-trading job scheduled at 9:35 AM ET (Mon-Fri)")

    import atexit
    atexit.register(lambda: _scheduler.shutdown(wait=False))
except ImportError:
    logger.warning("apscheduler not installed — daily job will not run automatically")


logger.info(
    "AI Trading Workstation started — mode=%s env=%s watchlist=%s",
    settings.TRADING_MODE,
    settings.ENVIRONMENT,
    settings.WATCHLIST,
)
