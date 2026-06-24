---
name: cerebras
description: Reference for Cerebras Cloud's free, ultra-fast LLM inference API (OpenAI-compatible, ~3000 tokens/sec, no credit card required). Use this skill whenever Cerebras, Cerebras Cloud, cerebras.ai, api.cerebras.ai, or its free models (gpt-oss-120b, zai-glm-4.7) come up -- for evaluating or adding an LLM provider, comparing free inference options against OpenRouter, debugging Cerebras rate limits or 429 errors, or writing any code that calls the Cerebras API. Always check this skill before writing Cerebras integration code: the model lineup and free-tier rate limits change over time, and this file lists the live docs to re-verify against.
---

# Cerebras Cloud Inference API

Cerebras runs open-weight LLMs on its own wafer-scale chips and exposes them through a
free, OpenAI-compatible HTTP API. The headline feature is raw speed (~3000 tokens/sec on
`gpt-oss-120b`, vs. a few hundred tokens/sec on most other free inference providers) — this
matters for anything latency-sensitive, like an interactive agent loop or a trading decision
that needs to run before a market window closes.

This file is a snapshot taken from Cerebras's own docs. Free-tier limits and the model
lineup are the kind of thing a provider tunes often, so before relying on an exact number,
re-check:

- Rate limits: https://inference-docs.cerebras.ai/support/rate-limits
- Model catalog: https://inference-docs.cerebras.ai/models/overview
- OpenAI-compat guide: https://inference-docs.cerebras.ai/resources/openai

## Getting an API key

Sign up at https://cloud.cerebras.ai — no credit card needed for the free tier. Put the key
in an env var, e.g. `CEREBRAS_API_KEY`, never hardcoded or committed.

## Calling the API

Cerebras supports two equally valid ways to call it. Pick whichever fits the codebase:

**Option A — reuse the `openai` SDK** (best if the project already talks to another
OpenAI-compatible provider, e.g. OpenRouter, and you want one client pattern for both —
just swap `base_url` and the API key env var):

```python
import os
import openai

client = openai.OpenAI(
    base_url="https://api.cerebras.ai/v1",
    api_key=os.environ.get("CEREBRAS_API_KEY"),
)

response = client.chat.completions.create(
    model="gpt-oss-120b",
    messages=[{"role": "user", "content": "..."}],
)
```

**Option B — dedicated Cerebras SDK** (`pip install cerebras_cloud_sdk`). Slightly more
ergonomic for Cerebras-specific (non-standard) parameters — see "Non-standard parameters"
below.

```python
import os
from cerebras.cloud.sdk import Cerebras

client = Cerebras(api_key=os.environ.get("CEREBRAS_API_KEY"))

response = client.chat.completions.create(
    model="gpt-oss-120b",
    messages=[{"role": "user", "content": "..."}],
)
```

Both support `stream=True`, tool/function calling, and structured outputs (JSON schema)
on `gpt-oss-120b`.

## Available free models (as of mid-2026)

| Model ID       | Params | Speed       | Status     | Notes                                   |
|----------------|--------|-------------|------------|------------------------------------------|
| `gpt-oss-120b` | 120B   | ~3000 tok/s | Production | OpenAI's open-weight model; tool calling, structured outputs, reasoning_effort param |
| `zai-glm-4.7`  | 355B   | ~1000 tok/s | Preview    | Eval only — Cerebras may pull preview models on short notice |

Context window on `gpt-oss-120b`: 65K tokens (free tier) / 131K tokens (paid tiers).
Max output: 32K tokens (free tier) / 40K tokens (paid tiers).

Get the live list any time with `GET /v1/models`.

## Free-tier rate limits

Cerebras's own docs page (`/support/rate-limits`) and the per-model page both state, as of
this writing:

| Model          | Requests/min | Input tokens/min | Tokens/day |
|----------------|--------------|-------------------|------------|
| `gpt-oss-120b` | 5            | 30,000            | 1,000,000  |
| `zai-glm-4.7`  | 5            | 30,000            | 1,000,000  |

Caveat: the prose summary on Cerebras's `gpt-oss-120b` model page currently says "30
requests/min, 60k input tokens/min" — which contradicts the structured rate-limit table on
that same page and the dedicated rate-limits page (both say 5 RPM / 30K). Treat 5 RPM as the
authoritative number unless you confirm otherwise by hitting the API and reading the
response headers (see below). Don't trust either number blindly for a workload that depends
on it — verify live.

5 requests/min is tight for anything that calls the model many times in a loop (e.g.
backtesting many historical decisions). 1M tokens/day is generous for a single live
decision job that runs a handful of times daily. Paid "Developer" (pay-as-you-go) tier
removes the daily/hourly caps: 1,000 RPM / 1M TPM for `gpt-oss-120b`, 500 RPM / 500K TPM for
`zai-glm-4.7`.

Rate limits apply per organization, not per API key.

### Reading live quota from response headers

Every response includes headers you can check instead of guessing at quota:

```
x-ratelimit-limit-requests-day
x-ratelimit-limit-tokens-minute
x-ratelimit-remaining-requests-day
x-ratelimit-remaining-tokens-minute
x-ratelimit-reset-requests-day
x-ratelimit-reset-tokens-minute
```

If you're building anything that calls Cerebras repeatedly (a batch job, a backtest loop),
read these headers and back off proactively rather than waiting for a 429.

## Cerebras-specific quirks worth knowing before integrating

- **System vs. developer role**: on Cerebras, both `system` and `developer` messages are
  mapped to the same developer-level instruction layer, which has *more* influence over
  the model than a plain OpenAI `system` message would. A system prompt that behaves one
  way on OpenAI/OpenRouter may behave more forcefully on Cerebras. Test prompts again after
  switching providers — don't assume identical behavior.
- **Non-standard parameters**: with the `openai` SDK, anything Cerebras-specific (e.g.
  `clear_thinking` for `zai-glm-4.7`) must go through `extra_body={...}`. With the native
  Cerebras SDK, you can just pass it as a normal keyword argument. Standard OpenAI params
  like `reasoning_effort` work directly either way.
- **`reasoning_effort`**: controls how much the model reasons before answering on
  `gpt-oss-120b`. Default is `"medium"`. Lower it for latency-sensitive calls.
- **Tool-call hallucination**: `gpt-oss-120b` has been observed inventing tool calls that
  weren't declared in the request. If you see this, Cerebras's own docs suggest reprompting
  with something like "you're hallucinating a tool call" to get it to self-correct.
- **`min_tokens`**: if set, the model may emit an end-of-sequence token early, which can
  break naive output parsers. Avoid relying on `min_tokens` unless you've tested the
  parsing path.

## When to reach for this vs. OpenRouter

Both are free, OpenAI-compatible gateways. Rough tradeoffs:

- **Cerebras** wins on raw speed (~3000 tok/s) and daily token budget (1M tokens/day flat).
  Its weak point is the 5 requests/min cap, which throttles anything that needs many
  sequential calls in a short window (e.g. iterating over years of backtest data quickly).
- **OpenRouter** (`openai/gpt-oss-120b:free`, as already used in this project) allows more
  requests/min (20) but a much lower request ceiling per day (50-1000 depending on lifetime
  credit purchases) and is request-limited rather than token-limited.

If a workload is bottlenecked by *request count* per day, OpenRouter's higher per-minute
rate helps short bursts but its daily request cap bites first. If a workload just needs a
handful of calls per day but each one should return fast, Cerebras's generous daily token
budget and speed are the better fit, as long as the 5 RPM ceiling isn't violated.

This project uses Cerebras directly for its LLM reasoning layer — `gpt-oss-120b` via
`https://api.cerebras.ai/v1`, configured through `LLM_API_KEY` / `LLM_BASE_URL` /
`LLM_MODEL` in `.env`. See `CLAUDE.md` and `planning/plan.md` section 9 for the
integration design and backtest rate-limit mitigations.
