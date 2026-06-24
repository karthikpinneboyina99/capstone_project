# backend/

FastAPI application: data ingestion, ML signal models, LLM reasoning layer, backtesting engine, paper trading executor, and the REST/WebSocket API consumed by the frontend.

Build order and full instructions live in `../planning/plan.md`. Do not write code here until you've read that file and know which phase you're on.

Expected structure (created during the build phases, not all at once):

```
backend/
├── app/
│   ├── main.py              # FastAPI app entrypoint
│   ├── core/                # config, settings, security
│   ├── api/                 # route handlers (signals, trades, backtests, portfolio)
│   ├── models/               # SQLAlchemy ORM models
│   ├── schemas/               # Pydantic request/response schemas
│   ├── services/
│   │   ├── data_ingestion/   # yfinance / Alpaca market data pullers
│   │   ├── features/         # technical indicator / feature engineering
│   │   ├── ml/                # model training + inference
│   │   ├── llm_reasoning/     # LLM decision layer (via OpenRouter, free model)
│   │   ├── backtesting/       # backtest engine
│   │   └── trading/           # Alpaca paper trading execution + risk checks
│   └── db/                    # session/engine setup, migrations entrypoint
├── requirements.txt
└── Dockerfile
```
