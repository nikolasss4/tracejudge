# Demo: customer-support agent

A small tool-calling agent for a fictional shop, in the spirit of tau-bench's retail domain.

- **Tools** (`tools.py`): `lookup_order`, `check_refund_policy`, `issue_refund`,
  `change_address`, `escalate_to_human`, over a mock order database (`data.py`).
- **Policy**: refunds within 30 days of delivery (60 if damaged), never for final-sale or
  undelivered orders, over $500 goes to a human; address changes only while processing; only the
  order's owner may act.
- **Two versions** (`prompts.py`): v2 is a "friendlier" rewrite of v1's system prompt that drops
  the instruction to check the policy before refunding.
- **Suite** (`suite.yaml`): 41 cases with deterministic expectations plus three LLM-judge
  criteria.

The agent runs on Claude (`SUPPORT_AGENT_MODEL=claude-sonnet-5-5`, needs `ANTHROPIC_API_KEY`) or
on `simulated.py`, a scripted stand-in that needs no key. The simulated model is keyword logic,
not an LLM; see the docstring in `simulated.py` for exactly what it does.

```bash
tracejudge eval examples/support_agent/suite.yaml --agent examples.support_agent.agent:run_v1 --label v1
tracejudge eval examples/support_agent/suite.yaml --agent examples.support_agent.agent:run_v2 --label v2
tracejudge diff v1 v2
```
