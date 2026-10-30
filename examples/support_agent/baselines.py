"""Trivial reference agents. They set a floor: a suite that these pass is not testing much."""

from typing import Any


def always_refuse(inp: dict[str, Any]) -> str:
    """Never calls a tool; politely declines everything."""
    return "I'm sorry, I can't help with that. Please contact support."
