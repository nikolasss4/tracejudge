# ADR 0004: What counts as a regression

**Status:** accepted

## Context

Each case runs N times (default 3) because agents are not deterministic. Comparing two runs
per trial would call every coin-flip a regression; comparing only aggregate pass rate hides
which behaviours broke.

## Decision

Per case, compare the share of passing trials:

- **regressed** – most trials passed in the baseline, at most half pass in the candidate;
- **fixed** – the reverse;
- **degraded / improved** – the share moved but the majority didn't flip.

The CI gate defaults to zero regressions and optionally a maximum pass-rate drop and cost
increase. Every report includes Fisher's exact test on trial counts for the whole run and a note
on what N trials per case can and cannot show (3 vs 3 can't reach p < 0.1 for a single case).

## Consequences

- One flaky trial doesn't fail a PR; a behaviour that consistently breaks does.
- Degradations are surfaced but don't gate by default; teams that care can gate on pass^k.
