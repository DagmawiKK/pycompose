"""The host's signal: state changed outside an action, so pull a fresh snapshot.

The host installs one sink per session. Python posts a data-only event to it
from the loop thread; the host answers by delivering that event back as an
ordinary action, and pulls the snapshot it produces.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

__all__ = ["install", "post"]

_lock = threading.Lock()
_sink: Callable[[str, str], None] | None = None
_admission: Callable[[str, str], bool] | None = None


def install(
    sink: Callable[[str, str], None] | None,
    admission: Callable[[str, str], bool] | None = None,
) -> None:
    """Set where signals go, or stop sending them.

    Args:
        sink: Receives an event id and its JSON payload, or None.
        admission: A host queue that reports whether it took the event; used
            instead of ``sink`` when given.
    """
    global _sink, _admission
    with _lock:
        _sink, _admission = sink, admission


def post(event: str, payload: str = "{}") -> bool:
    """Send one event to the host.

    Args:
        event: The event's id.
        payload: Its JSON payload.

    Returns:
        Whether a host took it; False when none is listening or its queue is full.
    """
    with _lock:
        sink, admission = _sink, _admission
    if admission is not None:
        return admission(event, payload)
    if sink is None:
        return False
    sink(event, payload)
    return True
