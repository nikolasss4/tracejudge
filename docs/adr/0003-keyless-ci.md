# ADR 0003: Keyless CI with a simulated model and recorded judge fixtures

**Status:** accepted

## Context

The repo's CI must run the eval suite on every PR (dogfooding the GitHub Action) without an API
key: forks get no secrets, and CI shouldn't spend money or flake on rate limits.

## Decision

- The demo agent runs on `examples/support_agent/simulated.py`, a scripted stand-in that reads
  the system prompt's rules and the tool results and decides the next action with keyword
  logic. It is deliberately sensitive to the same prompt change a real model is (dropping
  "check the policy before refunding"), and makes seeded slips so flakiness metrics are exercised.
- LLM-judge calls are keyed by a hash of the full request and can be recorded once
  (`--record`, needs a key) and replayed forever. A criterion with no fixture and no key is
  reported as **skipped**, never as passed.

## Consequences

- CI is deterministic, free and fork-safe.
- Numbers from the simulated model say nothing about real model quality, and every table that
  shows them says so. Real numbers come from `SUPPORT_AGENT_MODEL=claude-sonnet-5-5`.
- Any change to the judge prompt or the agent's transcript invalidates the relevant fixtures,
  which then show up as skipped until re-recorded. That is the honest failure mode.
