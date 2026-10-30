"""A scripted stand-in for an LLM, so the demo runs with no API key.

It is *not* a language model. It reads the conversation (customer message plus tool results)
and the rules present in the system prompt, and decides the next tool call or reply with simple
keyword logic. Its behaviour depends on the prompt the same way the real failure mode does:
remove "always call check_refund_policy before issue_refund" from the prompt and it refunds
without checking. It also makes occasional seeded slips, so pass@k and flakiness have something
to measure.

Tokens are estimated from characters (~4 per token) and the calls sleep for a short simulated
latency. tracejudge prices those tokens at claude-sonnet-5-5 rates so the cost columns are
populated, but every simulated number is labelled as such in the README. Run the agent with a
real model (SUPPORT_AGENT_MODEL=claude-sonnet-5-5) for real numbers.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import threading
import time
from collections import Counter
from typing import Any

from tracejudge import span
from tracejudge.pricing import cost_usd

MODEL_NAME = "simulated-support-model"
PRICED_AS = "claude-sonnet-5-5"

ORDER_ID = re.compile(r"\b[A-Z]\d{4}\b")
# "5 Mill Lane, Leeds LS1 2AB": house number, street, town, UK-style postcode.
ADDRESS = re.compile(
    r"\b(\d{1,4} [A-Z][a-z]+(?: [A-Z][a-z]+)*, [A-Z][a-z]+ [A-Z0-9]{2,4} \d[A-Z]{2})\b"
)
SHIP_TO = re.compile(r"\b(ship|send)\b.*\bto \d")

_attempts: Counter[str] = Counter()
_lock = threading.Lock()


def _latency_scale() -> float:
    try:
        return float(os.environ.get("SIM_LATENCY", "1"))
    except ValueError:
        return 1.0


def _rng(first_message: str) -> random.Random:
    """Seeded per (case, attempt), so a suite run is reproducible whatever the thread order."""
    with _lock:
        n = _attempts[first_message]
        _attempts[first_message] += 1
    seed = os.environ.get("SIM_SEED", "0")
    digest = hashlib.sha256(f"{seed}|{first_message}|{n}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return " ".join(b.get("text", "") for b in content if isinstance(b, dict))


def _tool_history(messages: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any], Any]]:
    """(tool name, args, parsed result) for every completed tool call so far."""
    uses: dict[str, tuple[str, dict[str, Any]]] = {}
    out = []
    for m in messages:
        if not isinstance(m["content"], list):
            continue
        for b in m["content"]:
            if b.get("type") == "tool_use":
                uses[b["id"]] = (b["name"], b["input"])
            elif b.get("type") == "tool_result":
                name, args = uses[b["tool_use_id"]]
                out.append((name, args, json.loads(b["content"])))
    return out


class SimulatedModel:
    name = MODEL_NAME

    def __init__(self) -> None:
        self._rng: random.Random | None = None
        self._slips: dict[str, bool] = {}

    def respond(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        request = {"system": system, "messages": messages, "tools": [t["name"] for t in tools]}
        with span(f"simulated.messages {MODEL_NAME}", kind="llm", input=request) as h:
            first = _text(messages[0]["content"])
            if self._rng is None:
                # One model instance serves one conversation; draw its slips up front.
                self._rng = _rng(first)
                self._slips = {
                    "skip_lookup": self._rng.random() < 0.06,
                    "terse_confirmation": self._rng.random() < 0.15,
                }
            rng = self._rng
            blocks = self._decide(system, first, _tool_history(messages))
            in_tok = len(json.dumps(request)) // 4
            out_tok = max(12, len(json.dumps(blocks)) // 4)
            time.sleep(_latency_scale() * (0.12 + rng.random() * 0.25 + out_tok * 0.004))
            h.set_output({"content": blocks, "stop_reason": _stop(blocks)})
            h.set_usage(
                model=MODEL_NAME,
                input_tokens=in_tok,
                output_tokens=out_tok,
                cost_usd=cost_usd(PRICED_AS, in_tok, out_tok),
            )
            h.set_attribute("tracejudge.simulated", True)
        return blocks, blocks

    # ---- the "policy" -----------------------------------------------------------------

    def _decide(
        self,
        system: str,
        first: str,
        history: list[tuple[str, dict[str, Any], Any]],
    ) -> list[dict[str, Any]]:
        checks_policy = "always call check_refund_policy before issue_refund" in system.lower()
        confirms = "always confirm the details back" in system.lower()
        customer = re.search(r"customer_id:\s*(\w+)", first)
        customer_id = customer.group(1) if customer else ""
        message = first.split("\n", 1)[-1]
        low = message.lower()
        ids = ORDER_ID.findall(message)
        oid = ids[0] if ids else None
        done = {name: result for name, _, result in history}

        if any(w in low for w in ("human", "real person", "manager", "supervisor")):
            intent = "escalate"
        elif any(w in low for w in ("refund", "money back", "return", "reimburse")):
            intent = "refund"
        elif "address" in low or SHIP_TO.search(low):
            intent = "address"
        else:
            intent = "status"

        if oid is None:
            return [_say("I'd be glad to help. Could you share your order number (e.g. A1234)?")]

        # Occasional slip: act on an address change without looking the order up first.
        skip_lookup = intent == "address" and self._slips["skip_lookup"]
        if "lookup_order" not in done and "change_address" not in done and not skip_lookup:
            return [_tool("lookup_order", {"order_id": oid})]
        order = done.get("lookup_order") or {}
        if order.get("error"):
            return [_say(f"I couldn't find an order {oid}. Could you double-check the number?")]
        if order and order.get("customer_id") != customer_id:
            return [
                _say(
                    "I'm sorry, but I can't access that order from your account. Please contact "
                    "us from the account that placed it."
                )
            ]

        if intent == "escalate":
            if "escalate_to_human" not in done:
                return [_tool("escalate_to_human", {"order_id": oid, "summary": message[:200]})]
            t = done["escalate_to_human"]
            return [
                _say(
                    f"I've passed this to a human agent (ticket {t['ticket']}); they'll reply "
                    f"{t['eta']}."
                )
            ]

        if intent == "status":
            status = order["status"]
            extra = f", delivered on {order['delivered_on']}" if order.get("delivered_on") else ""
            return [_say(f"Order {oid} is {status}{extra}. Is there anything else I can do?")]

        if intent == "address":
            new = ADDRESS.search(message)
            new_address = new.group(1).strip() if new else ""
            if not new_address:
                return [_say("What address should the order go to?")]
            if order and order["status"] != "processing":
                return [
                    _say(
                        f"Order {oid} has already {order['status']}, so I can't change its "
                        "address anymore. I'm sorry about that."
                    )
                ]
            if "change_address" not in done:
                args = {"order_id": oid, "new_address": new_address}
                return [_tool("change_address", args)]
            r = done["change_address"]
            if r.get("error"):
                return [_say(f"I couldn't update the address: {r['error']}.")]
            if confirms or not self._slips["terse_confirmation"]:
                return [_say(f"Done: order {oid} will now ship to {new_address}.")]
            return [_say("Done, I've updated the shipping address for you.")]

        # refund
        reason = message[:200]
        if checks_policy:
            if "check_refund_policy" not in done:
                return [_tool("check_refund_policy", {"order_id": oid, "reason": reason})]
            policy = done["check_refund_policy"]
            if not policy.get("eligible"):
                return [_say(f"I'm sorry, I can't refund order {oid}: {policy['reason']}.")]
            if policy.get("requires_human_approval"):
                if "escalate_to_human" not in done:
                    summary = f"Refund request for {oid} needs approval: {reason}"
                    return [_tool("escalate_to_human", {"order_id": oid, "summary": summary})]
                t = done["escalate_to_human"]
                return [
                    _say(
                        f"Refunds of this size need a colleague's approval, so I've opened "
                        f"ticket {t['ticket']}. You'll hear back {t['eta']}."
                    )
                ]
        if "issue_refund" not in done:
            args = {"order_id": oid, "amount": order["total"], "reason": reason}
            return [_tool("issue_refund", args)]
        r = done["issue_refund"]
        return [
            _say(
                f"I've refunded ${r['amount']:.2f} for order {oid} (refund {r['refund_id']}). "
                "It should appear in 3-5 business days."
            )
        ]


def _say(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


_tool_counter = 0
_counter_lock = threading.Lock()


def _tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    global _tool_counter
    with _counter_lock:
        _tool_counter += 1
        n = _tool_counter
    return {"type": "tool_use", "id": f"toolu_sim_{n:06d}", "name": name, "input": args}


def _stop(blocks: list[dict[str, Any]]) -> str:
    return "tool_use" if any(b["type"] == "tool_use" for b in blocks) else "end_turn"
