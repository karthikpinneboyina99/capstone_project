# AI Trading Workstation

An AI-assisted research and **paper-trading** platform for US stocks/ETFs. ML signal models + an LLM reasoning layer (free model via OpenRouter) produce explainable trade decisions, backtested on history and run live against Alpaca's paper trading API, surfaced in a React dashboard.

**Paper trading only. Not financial advice.**

## Start here

The full build plan — architecture, tech stack, database schema, and the phase-by-phase checklist — lives in [`planning/plan.md`](planning/plan.md). That file is the source of truth; this README is just the front door.

## Quick start (once Phase 0 is complete)

```bash
# Backend
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env   # fill in real keys, never commit this
uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

## Project structure

```
backend/      FastAPI app: data ingestion, ML models, LLM reasoning, backtesting, paper trading
database/     Schema reference + Alembic migrations
frontend/     React + Vite dashboard
planning/     plan.md — the full build plan and progress tracker
tests/        Backend (pytest) and frontend (Vitest) test suites
```

## Status

See the checklists in [`planning/plan.md`](planning/plan.md) for current progress phase by phase.
