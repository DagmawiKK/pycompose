"""Statement functions run as Python: what a drawing or a layout does, recorded.

A draw function is compiled for the host, but it is still Python. Run as Python
-- in a test, or to compare against the host -- each draw call it makes appends
itself to the recording in progress, so the result is the same list of calls
the host paints. A layout run as Python reads its children's sizes from the
run and records each child it places. Outside a run neither has anything to
act on.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import cast

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


Placement = tuple[int, float, float]
"""One child placed: its index, then x and y in px."""


class _Laying:
    """One layout run as Python: its children's measured sizes, and what it placed."""

    def __init__(self, sizes: Sequence[tuple[float, float]]) -> None:
        self.sizes = sizes
        self.placements: list[Placement] = []


_LAYING: ContextVar[_Laying | None] = ContextVar("laying", default=None)


def _laying(name: str) -> _Laying:
    laying = _LAYING.get()
    if laying is None:
        raise RuntimeError(f"{name}() reads only inside a host layout function")
    return laying


def place(index: int, x: float, y: float) -> None:
    """Record one child placed by the layout in progress.

    Args:
        index: The child's index.
        x: Its left edge, in px.
        y: Its top edge, in px.
    """
    _laying("place").placements.append((int(index), float(x), float(y)))


def measured(index: int) -> tuple[float, float]:
    """One child's measured size in the layout in progress; 0 out of range.

    Args:
        index: The child's index.

    Returns:
        Its width and height, in px.
    """
    sizes = _laying("child_width").sizes
    return sizes[index] if 0 <= index < len(sizes) else (0.0, 0.0)


def laid_out(
    function: Callable[..., object],
    max_width: float,
    max_height: float,
    sizes: Sequence[tuple[float, float]],
    *bound: object,
) -> tuple[tuple[float, float], list[Placement]]:
    """Run a layout function as Python and return its size and placements.

    Args:
        function: The layout function.
        max_width: The largest width it may take, in px.
        max_height: The largest height.
        sizes: Each child's measured width and height.
        *bound: Any arguments bound to it.

    Returns:
        The size it returned, and each child it placed, in order.
    """
    laying = _Laying(sizes)
    token = _LAYING.set(laying)
    try:
        size = cast(
            "Mapping[str, float]", function(max_width, max_height, len(sizes), *bound)
        )
    finally:
        _LAYING.reset(token)
    return (float(size["width"]), float(size["height"])), laying.placements
