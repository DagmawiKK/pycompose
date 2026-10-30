"""What a snapshot is expanded for, as the host's handshake stated it.

A ``Fallback`` asks it which components cannot be rendered; the wire sets it
for the length of a session's emission and validation.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Protocol


class RenderTarget(Protocol):
    """What a snapshot is expanded for: which components it cannot render."""

    @property
    def substituted(self) -> set[str]:
        """Types a stand-in took the place of, for the session's diagnostic."""
        ...

    def lacks(self, node_type: str) -> bool:
        """Report whether the target cannot render a component type."""
        ...


_target: ContextVar[RenderTarget | None] = ContextVar("target", default=None)


@contextmanager
def rendering_for(target: RenderTarget) -> Iterator[None]:
    """Expand and validate the snapshots inside for ``target``.

    Args:
        target: What the snapshots are for.

    Yields:
        None: While the target is current.
    """
    token = _target.set(target)
    try:
        yield
    finally:
        _target.reset(token)


def render_target() -> RenderTarget | None:
    """Return what the snapshot being expanded is for, if anything.

    Returns:
        The target, or None outside a session's emission.
    """
    return _target.get()
