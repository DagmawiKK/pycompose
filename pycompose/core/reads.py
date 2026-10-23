"""Which fields of the app's state a composable read while it was built.

A composable taking the whole session would otherwise re-run whenever any field
of it changed. Recording the fields it actually read lets the expansion memo
reuse its output while those fields are unchanged, however much else moved.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

__all__ = ["record", "recording"]

_log: ContextVar[list[tuple[object, str]] | None] = ContextVar("reads", default=None)


@contextmanager
def recording() -> Iterator[list[tuple[object, str]]]:
    """Collect every recorded read made inside the block.

    Yields:
        list[tuple[object, str]]: The reads, as (owner, field name), in the
            order they were made.
    """
    reads: list[tuple[object, str]] = []
    token = _log.set(reads)
    try:
        yield reads
    finally:
        _log.reset(token)


def record(owner: object, name: str) -> None:
    """Note one field read, when a block is recording.

    Args:
        owner: The object read.
        name: The field read.
    """
    reads = _log.get()
    if reads is not None:
        reads.append((owner, name))
