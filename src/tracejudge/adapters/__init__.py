"""Thin adapters that record LLM calls from provider SDKs as ``llm`` spans."""

from tracejudge.adapters.anthropic import instrument_anthropic
from tracejudge.adapters.openai import instrument_openai

__all__ = ["instrument_anthropic", "instrument_openai"]
