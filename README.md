# AI Trading Workstation

A paper-trading research platform for US stocks and ETFs that combines XGBoost ML signals with LLM-generated reasoning to produce explainable trade decisions. Price history is ingested via yfinance/Alpaca, 20 technical features are engineered per symbol per day, an XGBoost model scores each signal, and Cerebras `gpt-oss-120b` (~3000 tok/s) wraps the signal in a plain-English rationale before submitting a paper order to Alpaca. A React dashboard surfaces signals, decisions, live positions, and backtest results. This is a learning and portfolio project — all trading is paper only, no real money is ever touched.

**Paper trading only. Not financial advice.**

---

## Architecture

```
  External data
  ┌─────────────┐   ┌──────────────┐   ┌────────────┐
  │  yfinance   │   │ Alpaca Bars  │   │  News API  │
  └──────┬──────┘   └──────┬───────┘   └─────┬──────┘
         └─────────────────┴─────────────────┘
                           │
                  data_ingestion/ (loaders)
                           │
                    PostgreSQL (OHLCV,
                    bars, news, features)
                           │
              features/engineer.py (20 features:
              RSI, MACD, Bollinger, ATR, vol ratios…)
                           │
              ml/train.py + ml/predict.py
              (XGBoost, walk-forward cross-validation)
                           │
                    signal score [0-1]
                           │
              llm_reasoning/ (Cerebras gpt-oss-120b)
              + decision cache (uq_decision_cache)
                           │
               BUY / HOLD / SELL + rationale text
                           │
        ┌──────────────────┴──────────────────┐
        │                                     │
  backtesting/                      trading/executor.py
  (day-by-day replay,                (daily paper-trading
   D+1 fill price)                    cycle, Alpaca API)
        │                                     │
        └──────────────────┬──────────────────┘
                           │
                     React dashboard
          (Signals · Decisions · Trades · Backtests)
```

---

## Stack

| Layer | Technology |
|---|---|
| Backend API | FastAPI + SQLAlchemy 2.0 + Alembic |
| Database | PostgreSQL |
| ML | XGBoost, walk-forward cross-validation |
| LLM | Cerebras API (`gpt-oss-120b`, OpenAI-compatible) |
| Frontend | React 18 + TypeScript + Vite + TanStack Query v5 + Recharts + Tailwind CSS v3 |
| Tests | pytest (241 tests) + Playwright E2E (23 tests) |
| CI | GitHub Actions (pytest + npm build on every push) |
| Infra | Docker multi-stage builds + docker-compose |

---

## Quick Start (local dev, no Docker)

### Prerequisites

- Python 3.11+
- Node 20+
- PostgreSQL running locally (or via Docker — see below)

### 1. Clone and configure

```bash
git clone <repo-url>
cd "AI TRADING WORKSTATION"
cp .env.example .env   # fill in the keys — see Environment Variables below
```

### 2. Backend

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
# API available at http://localhost:8000
# Docs at http://localhost:8000/docs
```

### 3. Frontend (separate terminal)

```bash
cd frontend
npm install
npm run dev
# Dashboard at http://localhost:5173
```

---

## Docker Quick Start

Starts PostgreSQL, the FastAPI backend, and the Vite frontend together.

```bash
cp .env.example .env   # fill in keys first
docker compose up
```

The backend will run migrations automatically on startup. The dashboard is at `http://localhost:5173`.

---

## Running Tests

```bash
# Backend — 241 pytest tests
pytest tests/backend/

# Frontend E2E — 23 Playwright tests (mocked API routes, all 5 pages)
cd frontend && npm run test:e2e
```

Test coverage spans: feature engineering, ML inference, LLM response parsing (mocked), backtest metrics, risk management checks, and all 8 FastAPI routers.

---

## Key Design Decisions

- **Decision cache prevents runaway LLM costs in backtests.** The `llm_decisions` table has a unique index (`uq_decision_cache`) on `(symbol, signal_date, prompt_version)`. Before any Cerebras call the system checks the cache; a hit returns the stored decision instantly. This is mandatory because the free-tier rate limit is 5 RPM — without caching, a two-year backtest over 10 symbols would exhaust the daily quota before completing a single run.

- **D+1 fill price in the backtester eliminates lookahead bias.** Every backtest order fills at the next trading day's open price, never at the close of the bar that generated the signal. This is enforced in `backtesting/` and matches how the live executor works (signal generated after close, order submitted for next-day open).

- **Paper-endpoint assertion is enforced in two places.** `app/main.py` asserts `ALPACA_BASE_URL` contains `paper-api` at startup, and `AlpacaPaperClient.__init__` raises `ValueError` if the URL is the live endpoint. The application refuses to start if misconfigured.

---

## Environment Variables

Copy `.env.example` to `.env` and fill in the values below. Never commit `.env`.

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://postgres:postgres@localhost:5432/trading_workstation` |
| `ALPACA_API_KEY` | Alpaca paper trading API key | _(required)_ |
| `ALPACA_SECRET_KEY` | Alpaca paper trading secret | _(required)_ |
| `ALPACA_BASE_URL` | Must be the paper endpoint | `https://paper-api.alpaca.markets` |
| `LLM_API_KEY` | Cerebras API key | _(required)_ |
| `LLM_BASE_URL` | Cerebras API base URL | `https://api.cerebras.ai/v1` |
| `LLM_MODEL` | Cerebras model ID | `gpt-oss-120b` |
| `MASSIVE_API_KEY` | Polygon.io key for market data (optional — falls back to SimulatorProvider) | _(optional)_ |
| `MASSIVE_BASE_URL` | Polygon.io base URL | `https://api.polygon.io` |
| `NEWS_API_KEY` | NewsAPI.org key for news headlines | _(optional)_ |
| `ENVIRONMENT` | `development` or `production` | `development` |
| `TRADING_MODE` | Must be `paper` | `paper` |
| `MAX_POSITION_PCT` | Max single-position size as fraction of portfolio | `0.10` |
| `MAX_POSITIONS` | Maximum concurrent open positions | `8` |
| `DAILY_LOSS_LIMIT_PCT` | Daily drawdown limit before trading halts | `0.03` |
| `PROMPT_VERSION` | LLM prompt template version — increment to invalidate cache | `1` |
| `WATCHLIST` | JSON array of ticker symbols to trade | `["AAPL","MSFT","NVDA","GOOGL","AMZN","META","TSLA","SPY","QQQ","JPM"]` |

---

## Project Structure

```
backend/
  app/
    core/config.py              # Pydantic Settings v2 — all env vars
    models/                     # 9 SQLAlchemy models (bars, features, signals,
    |                           #   decisions, trades, positions, backtests…)
    api/routers/                # 8 FastAPI routers
    services/
      data_ingestion/           # yfinance + Alpaca + news loaders
      features/engineer.py      # 20 technical features
      ml/train.py               # XGBoost walk-forward cross-validation
      ml/predict.py             # Inference + signal scoring
      llm_reasoning/            # Cerebras decision engine + decision cache
      backtesting/              # Day-by-day replay engine + performance metrics
      trading/executor.py       # Daily paper-trading cycle
  alembic/                      # DB migrations
  requirements.txt
frontend/
  src/
    api/                        # axios client + TanStack Query hooks
    pages/                      # Dashboard, Signals, Decisions, Trades, Backtests
    components/                 # Recharts equity curve, signal cards
  e2e/                          # Playwright tests (23 passing)
  playwright.config.ts
.github/workflows/ci.yml        # pytest + npm build on every push
docker-compose.yml              # postgres + backend + frontend
planning/plan.md                # Source-of-truth build checklist
```

---

## Disclaimer

This is a learning and portfolio project built to demonstrate how ML signals and LLM reasoning can be combined into an automated decision loop. The XGBoost model uses standard technical indicators (RSI, MACD, Bollinger Bands, ATR, and volume ratios) that are widely published and may not produce alpha in live markets. Past backtest performance does not imply future results. All trading executes against Alpaca's paper trading API — no real money is ever at risk, and the codebase contains hard assertions to enforce this.
