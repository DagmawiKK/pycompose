"""Draw calls run as Python: what a draw function asks for, recorded in order.

A draw function is compiled for the host, but it is still Python. Run as Python
-- in a test, or to compare against the host -- each draw call it makes appends
itself to the recording in progress, so the result is the same list of calls
the host paints. Outside a recording a draw call has nothing to draw on.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

DrawCall = tuple[str, tuple[object, ...]]
"""One draw: the call's name and its arguments in the table's order."""

_RECORDING: ContextVar[list[DrawCall] | None] = ContextVar("drawing", default=None)


@contextmanager
def recording() -> Iterator[list[DrawCall]]:
    """Collect the draw calls made inside the block.

    Yields:
        list[DrawCall]: The list the calls are appended to.
    """
    calls: list[DrawCall] = []
    token = _RECORDING.set(calls)
    try:
        yield calls
    finally:
        _RECORDING.reset(token)


def record(name: str, args: tuple[object, ...]) -> None:
    """Append one draw call to the recording in progress.

    Args:
        name: The draw call's name.
        args: Its arguments, in the table's order.

    Raises:
        RuntimeError: Outside a draw function run as Python.
    """
    calls = _RECORDING.get()
    if calls is None:
        raise RuntimeError(f"{name}() draws only inside a host draw function")
    calls.append((name, args))


def drawn(function: Callable[..., object], *args: object) -> list[DrawCall]:
    """Run a draw function as Python and return what it drew.

    Args:
        function: The draw function.
        *args: The canvas's size, then any bound arguments.

    Returns:
        Its draw calls, in order.
    """
    with recording() as calls:
        function(*args)
    return calls
