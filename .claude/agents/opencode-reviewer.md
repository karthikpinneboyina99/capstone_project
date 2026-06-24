name:opencode reveiwer
description: This custom agent reviews code and provides feedback on improvements, best practices, and potential issues

you must be using different agent the required model for this agent is  opencode. The agent will analyze the code, identify areas for improvement, and suggest changes to enhance code quality and maintainability.the document that needs to be reviewed is planning/plan.md.Disclaimer:The code review should be only provided by sub agent not by claude. The agent will provide a detailed review of the code, highlighting any potential bugs, security vulnerabilities, and performance issues. It will also suggest refactoring opportunities and recommend best practices for coding standards. The agent will generate a comprehensive report summarizing the findings and recommendations for the code review.the review should be in the opencode-reviewer.md file.

---

# OpenCode Review Report — planning/plan.md

**Date:** 2026-06-24

---

## Executive Summary

The plan is well-structured, technically literate, and appropriate for a capstone project. The core architectural decisions are sound: the "one decision function, two callers" rule, the decision cache design, and the explicit lookahead-bias mitigations are all correct and clearly stated. The following review surfaces gaps and risks that could derail implementation or compromise the capstone's rigor — ordered by severity within each section.

---

## 1. Completeness and Clarity of Each Phase

### Strengths

- Every phase has a concrete checklist with pass/fail criteria, which is unusual for a planning document and directly prevents scope creep.
- The "Definition of Done" blocks are genuinely testable, not vague ("unit tests mock the OpenAI client and verify parsing/validation logic, including malformed-response handling").
- Design decisions are recorded with rationale in Section 18, which eliminates guessing during implementation.

### Gaps

**Phase 0 — Missing version-pinning step.** The `pip install` command lists packages by name without version pins. Given that `xgboost`, `alpaca-py`, and `ta` all have breaking changes across minor versions, the `requirements.txt` produced from an unpinned install will differ between machines and over time. The checklist should include pinning versions and committing the lockfile before writing any code. Recommended addition: add `pip-compile` (pip-tools) or at minimum require `pip freeze > backend/requirements.txt` immediately after install, then commit that file.

**Phase 2 — No error/retry policy for external data sources.** NewsAPI (100 req/day free tier) and yfinance (unofficial scraping) both fail silently or return partial data. The checklist has no item requiring retry logic, exponential backoff, or data-validation checks (e.g., "does the returned bar count match the expected trading-day count?"). A missing data day silently poisons feature computation.

**Phase 3 — API authentication is completely absent.** Section 15 says "no multi-user auth system," but the FastAPI backend exposes trade execution endpoints with no authentication at all. Even for a single-operator capstone, an unauthenticated `/jobs/run-daily` endpoint reachable from the public internet (Render/Railway deploy) is a meaningful risk. A single API key header check (read from `.env`) would close this with one function.

**Phase 5 — Model artifact storage location undefined.** The checklist says "save versioned model artifacts (e.g., `models/xgb_v1.json` + metadata)" but the directory structure in Section 6 does not include a `models/` directory anywhere. This ambiguity will cause inconsistency between how the training script saves artifacts and how the inference function loads them.

**Phase 8 — No market-hours guard.** The daily job is described as "timed to run shortly after market close or before next open," but there is no checklist item requiring the executor to verify that the market was open on the target date before placing orders. Running the job on a US market holiday will attempt to submit orders that will be rejected, and the error handling path is unspecified.

**Phase 11 — Deployment secrets management unspecified.** The checklist says "set environment variables/secrets on each platform (never in the repo)" but gives no guidance on which variables go to which service, or how to verify they are set correctly before the first production run. A secrets-verification startup check (log which env vars are present without logging their values) would prevent silent misconfiguration in production.

---

## 2. Architectural Risks and Gaps

### Risk A — Decision function purity is asserted but not enforced

Section 3 states "build the decision function once, as a pure function of (symbol, as_of_date, available_data), and call it from both places." This is the most important design rule in the document. However, the phase checklist has no item explicitly testing that the backtester and the live executor call the identical code path (not copies). The recommended mitigation: add a test in Phase 10 that imports both `services/backtesting/engine.py` and `services/trading/executor.py` and asserts they both call the same `decision_engine` function object (or at minimum the same module). Without this test, the two callers drift silently over time.

### Risk B — SSE endpoint design is underdeveloped

Phase 3 adds a `GET /stream/portfolio` SSE stub and says "wire it fully in Phase 8." This defers a significant architectural decision: FastAPI's `StreamingResponse` with SSE requires either a background task updating an async queue or a database polling loop. Neither is mentioned. If the daily job runs as a background job (APScheduler in-process), it needs a thread-safe mechanism to push updates to SSE clients. This should be designed in Phase 3, not punted entirely.

### Risk C — positions table has no unique constraint

The `positions` table is described with columns `instrument_id`, `mode`, and `backtest_run_id`, but there is no stated unique constraint on `(instrument_id, mode, backtest_run_id)`. Without it, a bug in the executor's upsert logic can create duplicate position rows, causing the portfolio value calculation to be wrong in a way that is not immediately obvious. Add a unique constraint on `(instrument_id, mode, backtest_run_id)` — where `backtest_run_id IS NULL` for paper-mode rows (a partial unique index in Postgres handles this cleanly).

### Risk D — portfolio_snapshots has no unique constraint on date + mode + run

Similarly, `portfolio_snapshots` lacks a stated unique constraint on `(as_of_date, mode, backtest_run_id)`. Running the daily job twice on the same day (e.g., after a restart) will insert duplicate snapshot rows, causing the equity curve to double-count a day.

### Risk E — No exit/sell signal design

The plan describes buy and sell actions but never specifies when the system generates a sell signal for an existing position. The LLM can return `"action": "sell"`, but what drives it to reconsider an open position? If the decision engine only runs for symbols generating a fresh buy candidate, it will never see symbols that are already held and should be exited. The backtester loop says "for each symbol on the watchlist: compute features... get a decision" which implies all symbols are evaluated every day — but this needs to be stated explicitly as a rule, and the executor must mirror it.

### Risk F — No transaction management around the daily job

The paper trading executor performs multiple writes: insert trade, update position, insert portfolio snapshot, update Alpaca order. If any of these fail mid-sequence, the DB will be in an inconsistent state (e.g., trade recorded but position not updated). The plan does not specify wrapping these writes in a single DB transaction. FastAPI's SQLAlchemy session should use `session.begin()` as a context manager around the full sequence.

---

## 3. Security Concerns

### S1 — No API authentication on the backend (High)

Repeated from Section 1 for emphasis. The backend will be deployed publicly on Render/Railway. The `/jobs/run-daily` endpoint, if unauthenticated, is effectively a public endpoint that can place paper orders and ingest data on demand. Add a simple `X-API-Key` header check in FastAPI's dependency injection system. One `.env` variable (`INTERNAL_API_KEY`) and one `Depends()` function is sufficient.

### S2 — raw_response stored in DB without size limit (Medium)

`llm_decisions.raw_response` is typed as JSON with no stated size constraint. A malformed or adversarially large LLM response could cause an unusually large DB row. Add a `CHECK (pg_column_size(raw_response) < 65536)` constraint or truncate the raw response before storing if it exceeds a threshold (e.g., 32 KB).

### S3 — `.env.example` content not specified (Low)

The plan says `.env.example` is tracked and contains placeholders, but never lists the full set of expected variables. A developer setting up the project for the first time will not know which variables are required. The `.env.example` file should contain every variable name used in `core/config.py`, including: `DATABASE_URL`, `ALPACA_API_KEY`, `ALPACA_API_SECRET`, `ALPACA_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `NEWS_API_KEY`, `MAX_POSITION_PCT`, `MAX_POSITIONS`, `DAILY_LOSS_LIMIT_PCT`, and `INTERNAL_API_KEY`.

### S4 — Alpaca paper-only assertion timing (Low)

The plan says "assert at startup that the Alpaca base URL is the paper endpoint." This is correct. However, "startup" should mean application startup (in `main.py` lifespan event or at import time in the trading module), not lazily checked at order-placement time. If the assertion is only in `executor.py`, a developer testing other parts of the app can misconfigure `ALPACA_BASE_URL` without triggering the check until an order is attempted.

---

## 4. Performance and Scalability Issues

### P1 — LLM rate-limit handling has no retry/backoff (High)

Section 9 acknowledges the Cerebras free tier is rate-limited but describes only the decision cache as a mitigation. There is no mention of retry-with-backoff when a 429 is returned. During a backtest that samples every N days, burst calls to the LLM (e.g., 10 symbols on the same sampled day) will hit 5 RPM limits and fail with unhandled exceptions. The LLM client wrapper must implement exponential backoff with jitter on 429 responses. The `tenacity` library integrates cleanly with the `openai` SDK for this.

### P2 — No DB index on news_articles.published_at (Medium)

The decision engine queries news headlines "for the symbol, latest 3-5 headlines." This query joins `news_articles` on `instrument_id` and orders by `published_at DESC`. Without an index on `(instrument_id, published_at DESC)`, this scan becomes a full table scan as the news table grows (100 requests/day * 15 symbols = 1500 rows/day, growing to ~500k rows over a year). Add this index in the schema spec.

### P3 — Feature computation at backtest time re-queries the full price history every day (Medium)

The backtester loop says "compute features using data ≤ D." If the feature computation function loads all price bars from the DB on every iteration (once per symbol per day), a 2-year backtest on 15 symbols = 15 * 500 days * 15 = 112,500 DB queries. The implementation should load the full price history per symbol once at the start of each backtest run and pass a pre-loaded DataFrame slice to the feature function. The plan does not mention this optimization; the interface spec for the decision function should include a `price_df` parameter rather than a date that triggers a DB query internally.

### P4 — No pagination on trade history and portfolio snapshot endpoints (Low)

The frontend Trades page shows "full trade history (paper), filterable by symbol/date." Over months of daily trading, this table can grow to thousands of rows. The API endpoint should return paginated results from day one; retrofitting pagination breaks the frontend contract after the fact.

---

## 5. Lookahead Bias Risks

The plan is thoughtful about lookahead bias. The following are the remaining edge cases:

### L1 — Feature computation uses "bars with timestamp ≤ D" but does not specify end-of-day (EOD) bar availability

The plan says "using that day's adjusted close." In practice, `yfinance` returns the adjusted close for date D, but the Alpaca historical bar for date D is not available until after market close (4:00 PM ET). The daily job needs to confirm that bar D is final before running features. If the job runs at 3:00 PM on date D and pulls the "latest" bar, it will get an intraday bar, not the adjusted EOD close. The executor's ingestion step must wait for or confirm the final EOD bar before proceeding.

### L2 — Walk-forward validation gap specification is missing

Section 8 describes "train on data up to time T, validate on T+1..T+k, roll forward" but does not specify the gap between T and T+1. If there is no gap, the label for a bar in the training set (forward 5-day return) can overlap with the first validation bar's features. A minimum gap of 5 trading days between training cutoff and validation start eliminates label overlap. This should be stated explicitly.

### L3 — News articles can introduce future-dated information

The `news_articles` table query for the decision engine at date D should filter `published_at <= D` (EOD). If the query uses "today's date" rather than `as_of_date`, live and backtest modes will diverge: the live run includes today's news, the backtest run might include news published after market close on D if the NewsAPI data was ingested in bulk. The query must always use `as_of_date` as the upper bound, not the current timestamp.

### L4 — Volume z-score denominator uses 20d average including day D

The volume z-score feature is described as "Volume z-score vs 20d average." If day D's own volume is included in the 20d rolling average used as the denominator, the z-score for day D is computed using partially post-hoc information (the rolling std includes D). Use a strictly lagged rolling mean/std: `df['volume'].shift(1).rolling(20).mean()`. The plan does not specify whether the rolling window is inclusive or exclusive of day D.

---

## 6. Missing Test Coverage Areas

The plan specifies test coverage at a high level. The following concrete gaps should be addressed in Phase 10:

- **Decision function identity test:** assert that `backtesting/engine.py` and `trading/executor.py` call the same underlying decision function, not copies. (See Risk A above.)
- **Data ingestion idempotency test:** run the yfinance loader twice for the same date range and assert that `price_bars` row count does not increase on the second run (upsert, not insert).
- **Decision cache test:** call the decision engine for the same (instrument, date, model_slug, prompt_version) twice and assert the LLM mock is called exactly once (cache hit on second call).
- **Risk-check boundary tests:** test each risk limit at exactly the boundary value (e.g., exactly 8 open positions, exactly 3% daily loss) — not just clearly under and clearly over.
- **Backtest fill at final day:** test that the backtester correctly excludes fills for the last day in the date range.
- **EOD bar availability guard test:** mock a scenario where the ingestion job runs before the EOD bar is available and assert the executor defers or raises.
- **LLM 429 retry test:** mock the Cerebras client to return a 429 on the first call and a valid response on the second; assert the decision engine retries and returns the valid response.
- **Portfolio snapshot deduplication:** run the daily executor twice on the same date and assert there is exactly one portfolio snapshot row for that date.
- **Sharpe ratio with all-zero returns:** assert the metrics module returns 0 (not NaN or divide-by-zero) when daily returns are constant.

---

## 7. Deployment and Operations Gaps

### O1 — No health check endpoint

Docker and Render both support health checks, but the plan does not include a `GET /healthz` endpoint. Without it, container orchestration cannot detect a degraded backend (e.g., DB connection lost) and will serve 500s to the frontend without restarting.

### O2 — No database backup plan

The plan deploys Postgres to Render or Railway. Neither service guarantees backup retention on free tiers. For a capstone demo, losing the decision history, trade log, and backtest results is recoverable but painful. The plan should include at minimum a `pg_dump` cron job to a local file or cloud storage bucket.

### O3 — docker-compose deferred to Phase 11 creates a late integration risk

Docker is introduced in the last substantive phase. If the backend has accumulated Dockerfile-incompatible assumptions (e.g., hardcoded local file paths for model artifacts, relative imports that work under `uvicorn` but not in a container), fixing them in Phase 11 under deadline pressure is high-risk. Recommend adding a minimal `docker-compose.yml` (Postgres + backend only, no model or ML) in Phase 1 so the DB migration is always run inside Docker from day one.

### O4 — No log rotation or structured logging specification

The plan mentions "basic error handling and logging middleware" in Phase 3 but does not specify log format (structured JSON vs plain text) or destination. In production on Render/Railway, structured JSON logs are ingested by the platform's log aggregator and become searchable. Plain text logs are not. Specify `structlog` or Python's built-in `logging` with a JSON formatter from Phase 3.

### O5 — GitHub Actions CI workflow not described in detail

Phase 11 says "add a GitHub Actions workflow running pytest." For a single-operator capstone, this is fine, but the workflow is unspecified. Missing from the description: whether the workflow uses a service container for Postgres (required for integration tests), how `LLM_API_KEY` is supplied (GitHub Actions secret), and whether the workflow builds the Docker image to catch Dockerfile regressions.

---

## 8. Best Practice Suggestions

### BP1 — Use Alembic's `--autogenerate` carefully

Alembic `--autogenerate` does not detect all schema changes (e.g., check constraints, partial indexes, column default changes on some DB types). Always inspect the generated migration before applying it. Add a comment to Phase 1 warning about this.

### BP2 — Pin the `PROMPT_VERSION` constant to a file, not a global

The plan says `PROMPT_VERSION` is "defined in the codebase." Make it the single source of truth by defining it in `services/llm_reasoning/prompt.py` only, and importing it everywhere else. If it is defined in multiple places or in a config file, the versions can drift.

### BP3 — Add a `models/` directory explicitly to the directory structure

The directory structure in Section 6 is missing a `models/` directory for ML artifacts. Omitting it from the spec means different developers will place artifacts in different locations (`backend/models/`, `backend/app/models/`, project root). Specify: `backend/models/` for artifact storage, `.gitignore`d by default (artifacts are not source code), with a `README` or `models/README.md` documenting the versioning convention.

### BP4 — Specify the risk-check execution order

Phase 11 lists three risk checks (`MAX_POSITION_PCT`, `MAX_POSITIONS`, `DAILY_LOSS_LIMIT_PCT`) but does not specify the order they are applied. If `MAX_POSITIONS` is checked before `DAILY_LOSS_LIMIT_PCT`, a day where the circuit breaker should fire may still add a position if fewer than 8 are open. The circuit breaker should be the first check, before any position-sizing logic.

### BP5 — Define "sell" semantics: full exit vs partial exit

The plan's output schema includes `position_size_pct` for both buy and sell actions. For a sell, does `position_size_pct` mean the fraction of the current position to sell, or the target portfolio allocation? This ambiguity will cause bugs at the executor boundary. Define explicitly: for `"action": "sell"`, `position_size_pct` is the fraction of the current holding to liquidate (1.0 = full exit). For `"action": "buy"`, it is the target allocation as a fraction of total portfolio value.

### BP6 — Consider `asyncpg` instead of `psycopg2-binary` for async FastAPI

The tech stack uses `psycopg2-binary` with SQLAlchemy, but FastAPI is async. Running synchronous `psycopg2` DB calls inside async FastAPI route handlers blocks the event loop. Use SQLAlchemy's async engine (`asyncpg` driver) or run all DB calls in a thread pool via `run_in_executor`. The plan should specify which approach is intended.

### BP7 — Specify the watchlist as a config file, not hardcoded

Phase 2 says "define the watchlist (e.g., AAPL, MSFT, NVDA, SPY, QQQ)." This should live in a config file (`watchlist.yaml` or an `instruments` table seeded by a fixture), not hardcoded in a Python file. The Settings page in the frontend is described as "watchlist management," which implies the watchlist is editable — but if it is hardcoded, the Settings page cannot actually change it.

---

## 9. Summary Table of Findings

| ID | Severity | Category | Finding |
|----|----------|----------|---------|
| A | High | Architecture | Decision function identity not enforced by tests — callers can drift |
| B | High | Architecture | SSE endpoint design deferred without specifying the concurrency mechanism |
| S1 | High | Security | No API authentication on any backend endpoint |
| P1 | High | Performance | LLM 429 rate-limit errors have no retry/backoff handling |
| L1 | High | Lookahead | EOD bar availability not guarded — intraday bar can be used as EOD |
| C | Medium | Architecture | positions table has no unique constraint — duplicate rows possible |
| D | Medium | Architecture | portfolio_snapshots has no unique constraint — double-counting possible |
| E | Medium | Architecture | Exit/sell signal trigger is implicit, not specified |
| F | Medium | Architecture | Daily executor writes are not wrapped in a DB transaction |
| P2 | Medium | Performance | Missing index on news_articles (instrument_id, published_at) |
| P3 | Medium | Performance | Feature computation re-queries full price history per day in backtest |
| L3 | Medium | Lookahead | News query must use as_of_date as upper bound, not current timestamp |
| L4 | Medium | Lookahead | Volume z-score rolling window may be inclusive of day D |
| O3 | Medium | Ops | Docker deferred to Phase 11 creates late integration risk |
| S2 | Medium | Security | raw_response has no size constraint |
| L2 | Low | Lookahead | Walk-forward gap not specified — label overlap possible |
| O1 | Low | Ops | No health check endpoint for container orchestration |
| O2 | Low | Ops | No database backup plan |
| O4 | Low | Ops | Log format unspecified (structured vs plain text) |
| O5 | Low | Ops | GitHub Actions CI workflow not fully specified |
| P4 | Low | Performance | No pagination on trade history / portfolio snapshot endpoints |
| S3 | Low | Security | .env.example variable list not specified |
| S4 | Low | Security | Paper-only assertion may fire too late (at order time, not startup) |
| BP3 | Low | Best Practice | models/ directory missing from directory structure spec |
| BP4 | Low | Best Practice | Risk-check execution order not specified |
| BP5 | Low | Best Practice | sell action's position_size_pct semantics ambiguous |
| BP6 | Low | Best Practice | psycopg2 blocks FastAPI event loop — asyncpg not specified |

---

*Report generated by opencode-reviewer agent. Reviewed document: `planning/plan.md`. Review date: 2026-06-24.*