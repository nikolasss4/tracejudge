"""tracejudge: evals and trace viewer for tool-calling agents."""

from tracejudge.sdk import capture, configure, current_span, span, trace

__version__ = "0.1.0"

__all__ = ["capture", "configure", "current_span", "span", "trace", "__version__"]
