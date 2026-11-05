"""Layout programs: where a ``Layout`` places its children, run by the host.

A ``Layout`` measures and places its children every time its constraints or
children change, so the placing runs on the host. The app writes it as a
``@host`` function of the largest size it may take and how many children it
has, which places each child and returns its own size::

    @host
    def column(max_width: float, max_height: float, count: int) -> Size:
        y = 0.0
        for i in range(count):
            place(i, 0, y)
            y = y + child_height(i)
        return Size(max_width, y)

Each child is measured first, within the layout's largest size, so the program
reads its width and height by index. A layout program is a statement program
(``statements.py``): its calls place a child and state the layout's size, and
a loop may run once per child.
"""

from __future__ import annotations

from typing import Final, cast

from pycompose.model.catalog.vocabulary import (
    LAYOUT_CALLS,
    LAYOUT_LIMITS,
    LAYOUT_SIGNATURES,
)
from pycompose.model.programs.functions import Signature, Type
from pycompose.model.programs.statements import (
    ProgramKind,
    validate_call,
    validate_statements,
)

LAYOUT: Final = "layout"
"""A layout program's result: the placements it makes rather than a value."""

MEASURED = ("number", "number", "integer")
"""What every layout program is called with: the largest width and height it
may take, in px, and how many children it has."""

KIND = ProgramKind(
    LAYOUT,
    cast("tuple[Type, ...]", MEASURED),
    cast("dict[str, tuple[Type, ...]]", LAYOUT_CALLS),
    LAYOUT_LIMITS,
    cast("dict[str, dict[tuple[Type, ...], Type]]", LAYOUT_SIGNATURES),
    children=True,
)
"""What a layout program may do."""


def validate_layout(value: object) -> Signature:
    """Check a layout program's wire form: statements, types and limits.

    Args:
        value: The ``{"type": "program", "result": "layout", ...}`` object.

    Returns:
        Its signature: the measured arguments, then any bound to it.
    """
    return validate_statements(value, KIND)


def validate_placement(value: object) -> None:
    """Check what a ``Layout`` places with: a layout program, or one bound.

    Args:
        value: The layout prop's wire value, its program in place.
    """
    validate_call(value, KIND)
