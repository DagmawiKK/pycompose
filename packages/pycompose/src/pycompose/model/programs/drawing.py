"""Draw programs: what a ``Canvas`` paints, written in Python, run by the host.

A ``Canvas`` calls its draw lambda every frame it redraws, so the drawing runs
on the host. The app writes it as a ``@host`` function of the canvas's size that
returns nothing, and calls the draw calls the pin's ``DrawScope`` declares::

    @host
    def ring(width: float, height: float) -> None:
        for i in range(12):
            angle = i * pi / 6
            x = width / 2 + cos(angle) * 40
            circle(0xFF6750A4, 6, x, height / 2 + sin(angle) * 40)

A draw program is a statement program (``statements.py``) whose calls are the
draw calls. Both validators bound a frame's work before it first runs: the
draw calls a program can make, counted through its loops, stay within
``DRAW_LIMITS``.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import cache
from typing import Any, Final, cast

from pycompose.model.catalog.lock import REGISTRY
from pycompose.model.catalog.vocabulary import DRAW_LIMITS
from pycompose.model.programs.functions import Signature, Type
from pycompose.model.programs.statements import (
    ProgramKind,
    validate_call,
    validate_statements,
)

DRAW: Final = "draw"
"""A draw program's result: what it paints rather than a value it gives."""

CANVAS = ("number", "number")
"""What every draw program is called with: the canvas's width and height, in px."""


def draws() -> Mapping[str, Mapping[str, Any]]:
    """The draw calls the pinned ``DrawScope`` declares.

    Returns:
        Per call name: its arguments, each with its type and any default.
    """
    return REGISTRY.sections.get("draws", {})


@cache
def draw_kind() -> ProgramKind:
    """What a draw program may do: the pin's draw calls, within ``DRAW_LIMITS``.

    Returns:
        The draw programs' kind.
    """
    calls = {
        name: tuple(cast("Type", a["type"]) for a in spec["arguments"])
        for name, spec in draws().items()
    }
    limits = {**DRAW_LIMITS, "calls": DRAW_LIMITS["draws"]}
    return ProgramKind(DRAW, cast("tuple[Type, ...]", CANVAS), calls, limits)


def validate_drawing(value: object) -> Signature:
    """Check a draw program's wire form: statements, types and limits.

    Args:
        value: The ``{"type": "program", "result": "draw", ...}`` object.

    Returns:
        Its signature: the canvas's size, then any arguments bound to it.
    """
    return validate_statements(value, draw_kind())


def validate_canvas(value: object) -> None:
    """Check what a canvas draws with: a drawing of its size, or one bound.

    Args:
        value: The draw prop's wire value, its program in place.
    """
    validate_call(value, draw_kind())
