"""Per-model token prices, used to put a dollar cost on LLM spans.

Prices are USD per million tokens (input, output). Unknown models get no cost rather than a
guessed one; add your own with :func:`register_price`.
"""

from __future__ import annotations

PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4-5": (1.0, 5.0),
}

# Cache reads bill at a tenth of the input price and 5-minute cache writes at 1.25x.
CACHE_READ_FACTOR = 0.1
CACHE_WRITE_FACTOR = 1.25


def register_price(model: str, input_per_mtok: float, output_per_mtok: float) -> None:
    PRICES[model] = (input_per_mtok, output_per_mtok)


def _lookup(model: str) -> tuple[float, float] | None:
    if model in PRICES:
        return PRICES[model]
    # Tolerate provider prefixes and suffixes such as "anthropic.claude-opus-5-5".
    for name in sorted(PRICES, key=len, reverse=True):
        if name in model:
            return PRICES[name]
    return None


def cost_usd(
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float | None:
    if not model:
        return None
    price = _lookup(model)
    if price is None:
        return None
    inp, out = price
    total = (
        input_tokens * inp
        + output_tokens * out
        + cache_read_tokens * inp * CACHE_READ_FACTOR
        + cache_write_tokens * inp * CACHE_WRITE_FACTOR
    )
    return total / 1e6
