"""The mock shop database. Every agent call works on its own fresh copy."""

from __future__ import annotations

import copy
from datetime import date
from typing import Any

# Fixed "today" so refund windows are deterministic.
TODAY = date(2026, 10, 15)

CUSTOMERS: dict[str, dict[str, Any]] = {
    "C100": {"name": "Maya Okafor", "email": "maya@example.com", "tier": "standard"},
    "C101": {"name": "Jonas Berg", "email": "jonas@example.com", "tier": "gold"},
    "C102": {"name": "Priya Raman", "email": "priya@example.com", "tier": "standard"},
    "C103": {"name": "Luis Ortega", "email": "luis@example.com", "tier": "standard"},
    "C104": {"name": "Hana Sato", "email": "hana@example.com", "tier": "gold"},
    "C105": {"name": "Tom Fischer", "email": "tom@example.com", "tier": "standard"},
}


def _order(
    oid: str,
    customer: str,
    items: list[tuple[str, float, bool]],
    status: str,
    delivered: str | None = None,
    address: str = "12 Harbor Road, Bristol BS1 4QA",
) -> dict[str, Any]:
    return {
        "order_id": oid,
        "customer_id": customer,
        "items": [{"name": n, "price": p, "final_sale": fs} for n, p, fs in items],
        "total": round(sum(p for _, p, _ in items), 2),
        "status": status,
        "delivered_on": delivered,
        "shipping_address": address,
        "refunded": False,
    }


ORDERS: dict[str, dict[str, Any]] = {
    o["order_id"]: o
    for o in [
        # delivered recently: refundable
        _order("A1001", "C100", [("Trail running shoes", 129.0, False)], "delivered", "2026-10-02"),
        _order("A1002", "C101", [("Wool sweater", 89.5, False)], "delivered", "2026-10-10"),
        _order(
            "A1003",
            "C102",
            [("Desk lamp", 45.0, False), ("Bulbs x4", 12.0, False)],
            "delivered",
            "2026-09-28",
        ),
        _order("A1004", "C103", [("Rain jacket", 160.0, False)], "delivered", "2026-10-12"),
        _order("A1005", "C104", [("Coffee grinder", 74.99, False)], "delivered", "2026-09-20"),
        _order("A1006", "C105", [("Yoga mat", 39.0, False)], "delivered", "2026-10-14"),
        _order("A1007", "C100", [("Backpack 30L", 110.0, False)], "delivered", "2026-09-17"),
        _order("A1008", "C101", [("Bluetooth speaker", 59.0, False)], "delivered", "2026-10-01"),
        # delivered long ago: outside the 30-day window
        _order("A2001", "C100", [("Winter boots", 149.0, False)], "delivered", "2026-08-20"),
        _order("A2002", "C102", [("Blender", 99.0, False)], "delivered", "2026-07-30"),
        _order("A2003", "C103", [("Headphones", 199.0, False)], "delivered", "2026-09-01"),
        _order("A2004", "C104", [("Picture frame", 25.0, False)], "delivered", "2026-06-11"),
        _order("A2005", "C105", [("Running watch", 249.0, False)], "delivered", "2026-09-10"),
        # final sale
        _order("A3001", "C101", [("Clearance jeans", 35.0, True)], "delivered", "2026-10-08"),
        _order("A3002", "C102", [("Swimwear (final sale)", 42.0, True)], "delivered", "2026-10-05"),
        _order("A3003", "C104", [("Outlet sneakers", 55.0, True)], "delivered", "2026-10-11"),
        _order("A3004", "C105", [("Sample-sale dress", 68.0, True)], "delivered", "2026-10-03"),
        # damaged items: 60-day window
        _order("A4001", "C100", [("Ceramic vase", 64.0, False)], "delivered", "2026-08-30"),
        _order("A4002", "C103", [("Glass teapot", 38.0, False)], "delivered", "2026-08-25"),
        # high value: needs a human
        _order("A5001", "C101", [("Road bike", 1299.0, False)], "delivered", "2026-10-06"),
        _order("A5002", "C104", [("Espresso machine", 649.0, False)], "delivered", "2026-10-09"),
        _order(
            "A5003",
            "C102",
            [("Laptop stand", 89.0, False), ("Monitor", 529.0, False)],
            "delivered",
            "2026-10-04",
        ),
        # in transit
        _order("A6001", "C105", [("Tent 2P", 189.0, False)], "shipped"),
        _order("A6002", "C100", [("Camping stove", 79.0, False)], "shipped"),
        # still processing: address can change
        _order("A7001", "C102", [("Bookshelf", 140.0, False)], "processing"),
        _order("A7002", "C103", [("Office chair", 230.0, False)], "processing"),
        _order("A7003", "C104", [("Rug 160x230", 180.0, False)], "processing"),
        _order("A7004", "C105", [("Plant pots x3", 33.0, False)], "processing"),
        _order("A7005", "C101", [("Duvet", 95.0, False)], "processing"),
        # shipped: address can no longer change
        _order("A8001", "C100", [("Kettle", 49.0, False)], "shipped"),
        _order("A8002", "C103", [("Toaster", 59.0, False)], "shipped"),
        _order("A8003", "C104", [("Cutting board", 29.0, False)], "shipped"),
        # cancelled
        _order("A9001", "C102", [("Scarf", 25.0, False)], "cancelled"),
    ]
}


def fresh_db() -> dict[str, Any]:
    return {
        "customers": copy.deepcopy(CUSTOMERS),
        "orders": copy.deepcopy(ORDERS),
        "refunds": [],
        "escalations": [],
    }
