"""Trace ids: which host input a piece of work, a failure or a pass belongs to.

The host may name each input with a trace id. It is set for the input's pass,
and every task the pass launches inherits it, because an asyncio task copies
the context it starts in; a failure reported from that task carries it too.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

__all__ = ["current_trace", "tracing"]

_TRACE: ContextVar[str | None] = ContextVar("pycompose_trace", default=None)


def current_trace() -> str | None:
    """Return the trace id of the input being handled, or None.

    Returns:
        The trace id the host sent with the input, if any.
    """
    return _TRACE.get()


@contextmanager
def tracing(trace: str | None) -> Iterator[None]:
    """Attribute everything inside the block, and what it launches, to ``trace``.

    Args:
        trace: The input's trace id, or None when the host sent none.
    """
    token = _TRACE.set(trace)
    try:
        yield
    finally:
        _TRACE.reset(token)
