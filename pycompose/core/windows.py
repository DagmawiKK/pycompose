"""The windows of each lazy container the host has asked for (ADR-0043).

A lazy container states its item count and composes only the items the host
asked to see. The session holds the latest request per container; emission
reads it from here while it builds the containers.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar

__all__ = ["DEFAULT_WINDOW", "MAX_WINDOW", "window_for", "windows"]

DEFAULT_WINDOW = 40
"""Items composed before the host has said what it shows."""

MAX_WINDOW = 400
"""The most items one request may ask for, so a request cannot compose everything."""

_requested: ContextVar[Mapping[str, tuple[int, int]]] = ContextVar(
    "windows", default={}
)


@contextmanager
def windows(requested: Mapping[str, tuple[int, int]]) -> Iterator[None]:
    """Make the host's requested windows visible to the containers built inside.

    Args:
        requested: First and last index wanted, by container key.

    Yields:
        None: While the windows are visible.
    """
    token = _requested.set(requested)
    try:
        yield
    finally:
        _requested.reset(token)


def window_for(key: str, count: int) -> range:
    """Return the item indexes a container should compose.

    Args:
        key: The container's window key.
        count: How many items it has.

    Returns:
        The requested window clamped to the items and to MAX_WINDOW, or the
        first DEFAULT_WINDOW items when the host has asked for none.
    """
    first, last = _requested.get().get(key, (0, DEFAULT_WINDOW - 1))
    start = max(0, min(first, count))
    return range(start, min(count, last + 1, start + MAX_WINDOW))
