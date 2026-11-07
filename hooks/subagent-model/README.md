# Subagent model and cache routing

Set up on 2026-11-07 to cut what subagents cost.

## Why

An audit of the logs on 2026-11-07 found:

- Subagents were about 82% of model spend, price-weighted. Most of it came from long implementation and rebuild jobs.
- 316 of 322 subagent calls named no model, so they all ran on Opus, the most expensive model in use.
- Subagents used the 5-minute prompt cache, so any pause over 5 minutes meant writing the whole conversation again.

Prices per million tokens, input / output: Opus $4 / $20, Sonnet $2 / $10, Haiku $0.10 / $0.50.

## What is in place

| Piece | Where | Effect |
|---|---|---|
| Sonnet default | `CLAUDE_CODE_SUBAGENT_MODEL=sonnet` in `setup/settings.hooks.json` `env` | A subagent started with no model runs on Sonnet, not Opus. |
| Model per step | the `plan-implement`, `plan-commit`, `plan-review`, `wrap-up`, `critique`, `plan-create`, `explain-visually` and `doc-sync` skills | Each subagent these skills start names its own model (see the table below). |
| This hook | `subagent_model.py`, a PreToolUse hook on the `Agent` tool | When a subagent is started with no model, the hook picks one from its type and description using keyword rules. |
| 1-hour cache | `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL=1h` in `setup/settings.hooks.json` `env` | A subagent's cache survives pauses of up to an hour. |

Model chosen at each step of the skills:

| Model | Steps |
|---|---|
| Haiku | commit, push, cold-read checks |
| Sonnet | implementation, PR text, merges, docs, pages, research |
| Opus | review, challenge and mediator in `critique`, hard implementation phases (statistics, numerical, geometry, cross-cutting refactors) |

`plan-implement` moves a phase to Opus after it fails its checks twice on Sonnet.

## Evidence

Anthropic's own measurements: an Opus manager with Sonnet subagents matched Opus alone at about a third less cost. Haiku subagents on coding lost about 4 points of pass rate.

**1-hour cache.** We replayed 1,412 subagent conversations from 2026-09-01 to 2026-11-07 under both cache lifetimes. The script is `cache_sim.py`, kept in the session scratchpad.

| Cache lifetime | Cost | Change |
|---|---|---|
| 5 minutes | $6,650 | — |
| 1 hour | $5,990 | −9.9% |

With a cache-read price of 0.05× instead of 0.10×, the saving is 15.3%. Short jobs pay more under the 1-hour cache, but long jobs that pause save more than that.

**Keepwarm.** The cache-tax keepwarm plugin pings only the main conversation and cannot warm subagents, so it does not help here.

## Hook rules

| When | Result |
|---|---|
| The call already names a model, or the agent type sets one in its frontmatter | Left unchanged |
| Type is `Explore` or `web-fetch` | Haiku |
| Type is `Plan` | Opus |
| Type or description mentions review, audit, critique, challenge, mediat, statistic, estimator, architect, design, root-cause, debug or diagnos | Opus |
| Description mentions commit, push, git, format, lint, link-check, lookup, find, search or list, and none of implement, fix, write or run | Haiku |
| Anything else | Sonnet |

Every decision is appended to `~/.claude/hooks/subagent-model.jsonl`, which is the audit trail. If the hook fails, it writes the error to stderr and the log, exits 1 without blocking the call, and the Sonnet default applies.

Tests: `python -m pytest test_subagent_model.py`
