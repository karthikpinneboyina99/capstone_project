# AI Trading Workstation

An AI-assisted research and **paper-trading** platform for US stocks/ETFs: ML signal models + an LLM reasoning layer (Cerebras free tier — `gpt-oss-120b` at ~3000 tok/s) produce explainable trade decisions, backtested and then run live against Alpaca's paper trading API, surfaced in a React dashboard.

The full plan — architecture, tech stack, database schema, and the phase-by-phase build checklist — is imported below. Treat it as the source of truth.

`@planning/plan.md`

The market data component is completed and is summarized in the file `planning/MARKET_DATA_SUMMARY.md` amd more details are in the `planning/archive` folder.consult these docs only when required.The remainder of the platform is still to be developed.

## Rules for working in this repo

- Before writing any code, check which phase of `planning/plan.md` is active (first unchecked checkbox under "13. Build Phases"). Don't skip ahead.
- After completing a checklist item, update the checkbox in `planning/plan.md` in the same change.
- This is paper trading only. Never implement a live/real-money order path. Assert at startup that the Alpaca base URL is the paper endpoint.
- LLM calls go through **Cerebras** (OpenAI-compatible API). Use the `openai` package with `base_url=https://api.cerebras.ai/v1` and the `LLM_API_KEY` env var; model is `gpt-oss-120b` (see `LLM_MODEL` in `.env`). Free tier is rate-limited (5 RPM, 1M tokens/day) — the decision cache in plan.md section 9 is mandatory for backtesting.
- Never commit `.env` or real API keys. Only `.env.example` with placeholders is tracked.
- The backtester and the live paper-trading executor must call the same decision function (features → ML signal → LLM decision). Don't let them drift apart.
- Run the relevant tests before marking a phase's checklist item done.
- Keep the README and this plan in sync with what's actually built.
