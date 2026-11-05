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

A draw program's body is a list of statements: a draw call, an ``if`` whose
branches are statements, or a loop of a literal count whose index the body
reads. Expressions are the value functions' (``functions.py``). Both validators
bound a frame's work before it first runs: the draw calls a program can make,
counted through its loops, stay within ``DRAW_LIMITS``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final, cast

from pycompose.errors import IrValidationError
from pycompose.model.catalog.lock import REGISTRY
from pycompose.model.catalog.vocabulary import DRAW_LIMITS, FUNCTION_LIMITS
from pycompose.model.programs.bound import valid_value
from pycompose.model.programs.functions import TYPES, Signature, Type, Walk

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


def validate_drawing(value: object) -> Signature:
    """Check a draw program's wire form: statements, types and limits.

    Args:
        value: The ``{"type": "program", "result": "draw", ...}`` object.

    Returns:
        Its signature: the canvas's size, then any arguments bound to it.

    Raises:
        IrValidationError: If the program is malformed, mistyped or too large.
    """
    if not isinstance(value, Mapping) or set(value) != {
        "type",
        "params",
        "result",
        "body",
    }:
        raise IrValidationError("a program is {type: program, params, result, body}")
    params = value["params"]
    if (
        value["type"] != "program"
        or value["result"] != DRAW
        or not isinstance(params, list | tuple)
        or tuple(params[:2]) != CANVAS
        or len(params) > FUNCTION_LIMITS["arguments"]
        or any(param not in TYPES for param in params)
    ):
        raise IrValidationError("a draw program takes the canvas's size, then types")
    signature = Signature(cast("tuple[Type, ...]", tuple(params)), DRAW)
    _Statements(signature.params).block(value["body"], 1)
    return signature


def validate_canvas(value: object) -> None:
    """Check what a canvas draws with: a drawing of its size, or one bound.

    A drawing that reads more than the canvas's size has the rest bound, as
    ``{"type": "bound", "program": ..., "args": [...]}``.

    Args:
        value: The draw prop's wire value.

    Raises:
        IrValidationError: If it is no drawing, or its bound arguments do not
            fill its remaining parameters with their types.
    """
    bound = isinstance(value, Mapping) and value.get("type") == "bound"
    if bound and set(cast("Mapping[str, object]", value)) != {
        "type",
        "program",
        "args",
    }:
        raise IrValidationError("a bound drawing is {type: bound, program, args}")
    program = cast("Mapping[str, object]", value)["program"] if bound else value
    args = cast("Mapping[str, object]", value)["args"] if bound else []
    rest = validate_drawing(program).params[len(CANVAS) :]
    if not isinstance(args, list | tuple) or len(args) != len(rest):
        raise IrValidationError(f"a drawing needs {len(rest)} bound arguments")
    if not all(valid_value(t, a) for t, a in zip(rest, args, strict=True)):
        raise IrValidationError(f"a drawing's bound arguments are {list(rest)}")


class _Statements:
    """Checks one body's statements, bounding the draws a frame can make."""

    def __init__(self, params: tuple[Type, ...]) -> None:
        self.expressions = Walk(params, DRAW_LIMITS["nodes"])
        self.draws = 0

    def block(self, statements: object, times: int) -> None:
        if not isinstance(statements, list | tuple):
            raise IrValidationError("a draw program's body is a list of statements")
        for statement in statements:
            self.statement(statement, times)

    def statement(self, node: object, times: int) -> None:
        if not isinstance(node, Mapping):
            raise IrValidationError("a draw statement is an object")
        keys = set(node)
        if keys == {"draw", "args"}:
            self.draw(node, times)
        elif keys == {"if", "then", "else"}:
            self.expect(node["if"], "boolean", "an if's test")
            self.block(node["then"], times)
            self.block(node["else"], times)
        elif keys == {"repeat", "body"}:
            self.repeat(node, times)
        else:
            raise IrValidationError(f"unknown draw statement {sorted(keys)}")

    def draw(self, node: Mapping[str, object], times: int) -> None:
        call = draws().get(str(node["draw"]))
        args = node["args"]
        if call is None or not isinstance(args, list | tuple):
            raise IrValidationError(f"unknown draw call {node['draw']!r}")
        wanted = cast("list[Mapping[str, object]]", call["arguments"])
        if len(args) != len(wanted):
            raise IrValidationError(f"{node['draw']} takes {len(wanted)} arguments")
        for arg, spec in zip(args, wanted, strict=True):
            self.expect(
                arg, cast("Type", spec["type"]), f"{node['draw']}.{spec['name']}"
            )
        self.draws += times
        if self.draws > DRAW_LIMITS["draws"]:
            raise IrValidationError(f"a frame could make more draws than {DRAW_LIMITS}")

    def repeat(self, node: Mapping[str, object], times: int) -> None:
        count = node["repeat"]
        if (
            type(count) is not int
            or not 0 <= count <= DRAW_LIMITS["repeat"]
            or self.expressions.loops >= DRAW_LIMITS["loops"]
        ):
            raise IrValidationError(f"a loop runs a literal count within {DRAW_LIMITS}")
        self.expressions.loops += 1
        self.block(node["body"], times * count)
        self.expressions.loops -= 1

    def expect(self, node: object, wanted: Type, what: str) -> None:
        given = self.expressions.type(node, 1)
        if given != wanted:
            raise IrValidationError(f"{what} takes a {wanted}, not a {given}")
