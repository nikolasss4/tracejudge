"""Mock tools. Each is traced as a ``tool`` span, so tracejudge sees name, args and result."""

from __future__ import annotations

from contextvars import ContextVar
from datetime import date
from typing import Any

from examples.support_agent.data import TODAY
from tracejudge import trace

_db: ContextVar[dict[str, Any]] = ContextVar("support_db")

REFUND_WINDOW_DAYS = 30
DAMAGED_WINDOW_DAYS = 60
HUMAN_APPROVAL_OVER = 500.0


def use_db(db: dict[str, Any]) -> None:
    _db.set(db)


def _orders() -> dict[str, dict[str, Any]]:
    return _db.get()["orders"]


@trace(kind="tool")
def lookup_order(order_id: str) -> dict[str, Any]:
    order = _orders().get(order_id.strip().upper())
    if order is None:
        return {"error": f"no order {order_id}"}
    return dict(order)


@trace(kind="tool")
def check_refund_policy(order_id: str, reason: str) -> dict[str, Any]:
    order = _orders().get(order_id)
    if order is None:
        return {"error": f"no order {order_id}"}
    if order["refunded"]:
        return {"eligible": False, "reason": "already refunded"}
    if order["status"] != "delivered":
        return {"eligible": False, "reason": f"order is {order['status']}, not delivered yet"}
    if any(i["final_sale"] for i in order["items"]):
        return {"eligible": False, "reason": "final-sale items cannot be refunded"}
    age = (TODAY - date.fromisoformat(order["delivered_on"])).days
    damaged = "damag" in reason.lower() or "broken" in reason.lower()
    window = DAMAGED_WINDOW_DAYS if damaged else REFUND_WINDOW_DAYS
    if age > window:
        return {
            "eligible": False,
            "reason": f"delivered {age} days ago; the refund window is {window} days",
        }
    if order["total"] > HUMAN_APPROVAL_OVER:
        return {
            "eligible": True,
            "requires_human_approval": True,
            "reason": f"refunds over ${HUMAN_APPROVAL_OVER:.0f} need a human agent",
            "max_amount": order["total"],
        }
    return {"eligible": True, "requires_human_approval": False, "max_amount": order["total"]}


@trace(kind="tool")
def issue_refund(order_id: str, amount: float, reason: str) -> dict[str, Any]:
    order = _orders().get(order_id)
    if order is None:
        return {"error": f"no order {order_id}"}
    if amount > order["total"]:
        return {"error": "amount exceeds order total"}
    order["refunded"] = True
    refund_id = f"R-{order_id}"
    _db.get()["refunds"].append({"refund_id": refund_id, "order_id": order_id, "amount": amount})
    return {"refund_id": refund_id, "amount": amount, "status": "issued"}


@trace(kind="tool")
def change_address(order_id: str, new_address: str) -> dict[str, Any]:
    order = _orders().get(order_id)
    if order is None:
        return {"error": f"no order {order_id}"}
    if order["status"] != "processing":
        return {"error": f"order is {order['status']}; address can no longer be changed"}
    order["shipping_address"] = new_address
    return {"order_id": order_id, "shipping_address": new_address, "status": "updated"}


@trace(kind="tool")
def escalate_to_human(order_id: str, summary: str) -> dict[str, Any]:
    ticket = f"T-{len(_db.get()['escalations']) + 1:04d}"
    _db.get()["escalations"].append({"ticket": ticket, "order_id": order_id, "summary": summary})
    return {"ticket": ticket, "eta": "within 24 hours"}


TOOLS = {
    "lookup_order": lookup_order,
    "check_refund_policy": check_refund_policy,
    "issue_refund": issue_refund,
    "change_address": change_address,
    "escalate_to_human": escalate_to_human,
}


def _schema(props: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


STR = {"type": "string"}
TOOL_DEFS = [
    {
        "name": "lookup_order",
        "description": "Look up an order by id. Returns customer, items, total, status, "
        "delivery date and shipping address.",
        "input_schema": _schema({"order_id": STR}),
    },
    {
        "name": "check_refund_policy",
        "description": "Check whether an order can be refunded under the refund policy, "
        "given the customer's reason. Returns eligible, reason and whether a human must approve.",
        "input_schema": _schema({"order_id": STR, "reason": STR}),
    },
    {
        "name": "issue_refund",
        "description": "Refund an order to the original payment method.",
        "input_schema": _schema({"order_id": STR, "amount": {"type": "number"}, "reason": STR}),
    },
    {
        "name": "change_address",
        "description": "Change the shipping address of an order.",
        "input_schema": _schema({"order_id": STR, "new_address": STR}),
    },
    {
        "name": "escalate_to_human",
        "description": "Hand the conversation to a human support agent.",
        "input_schema": _schema({"order_id": STR, "summary": STR}),
    },
]
for _t in TOOL_DEFS:
    _t["strict"] = True
