# frontend/

React + Vite dashboard: portfolio overview, equity curve, live signals feed with the LLM's natural-language rationale, trade history, and a backtest runner/results viewer.

Full UI spec (pages, components, data flow) is in `../planning/plan.md`, section "Frontend Dashboard". This folder stays empty until Phase 10.

Expected structure:

```
frontend/
├── src/
│   ├── components/     # Chart, SignalCard, PortfolioSummary, TradeTable, etc.
│   ├── pages/           # Dashboard, Signals, Trades, Backtests, Settings
│   ├── hooks/           # data-fetching hooks (React Query)
│   └── api/             # typed API client for the FastAPI backend
├── package.json
└── Dockerfile
```
