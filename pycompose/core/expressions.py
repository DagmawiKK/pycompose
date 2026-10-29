"""Expressions over holder streams, evaluated by the host every frame (plan 31 §6).

Python states desired values and hears settled reports; an expression is the
one thing it hands the host to evaluate on its own, frame by frame, so a prop
can follow a gesture with no Python in the loop::

    ModalNavigationDrawer(
        key="nav",
        scrim_color=Stream("nav", "progress").times(0.6).as_alpha("#000000"),
        ...
    )

The vocabulary is closed and total (``EXPRESSION_OPS``): numbers combine by
arithmetic and clamp, and become a colour as a colour's alpha or as a mix of
two colours. Expressions are type-checked as they are built, and the wire form
is checked again by both validators, within ``EXPRESSION_LIMITS``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pycompose.contract.registry_vocabulary import (
    EXPRESSION_LIMITS,
    EXPRESSION_OPS,
    STATE_STREAMS,
)
from pycompose.errors import IrValidationError

Kind = Literal["number", "color"]
_COLOR = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})")
_STREAMS = frozenset(name for names in STATE_STREAMS.values() for name in names)


@dataclass(frozen=True, slots=True)
class Expression:
    """A typed expression; build one from :func:`Stream` and its methods.

    Attributes:
        node: The wire node, a JSON object.
        kind: ``number`` or ``color``.
    """

    node: Mapping[str, Any]
    kind: Kind

    def times(self, other: float | Expression) -> Expression:
        """Multiply this number by another.

        Args:
            other: A number or a number expression.

        Returns:
            The product.
        """
        return _arithmetic("times", self, other)

    def plus(self, other: float | Expression) -> Expression:
        """Add another number to this one.

        Args:
            other: A number or a number expression.

        Returns:
            The sum.
        """
        return _arithmetic("plus", self, other)

    def minus(self, other: float | Expression) -> Expression:
        """Subtract another number from this one.

        Args:
            other: A number or a number expression.

        Returns:
            The difference.
        """
        return _arithmetic("minus", self, other)

    def clamp(self, low: float, high: float) -> Expression:
        """Keep this number between two bounds.

        Args:
            low: The smallest result.
            high: The largest result.

        Returns:
            The clamped number.

        Raises:
            ValueError: If ``low`` exceeds ``high``.
        """
        if low > high:
            raise ValueError(f"clamp bounds are reversed: {low} > {high}")
        return _node(
            "number",
            {
                "op": "clamp",
                "args": [self._number().node, _literal(low), _literal(high)],
            },
        )

    def as_alpha(self, color: str) -> Expression:
        """Use this number, clamped to 0..1, as the alpha of a colour.

        Args:
            color: ``#RRGGBB`` or ``#AARRGGBB``.

        Returns:
            A colour expression.
        """
        return _node(
            "color",
            {"op": "alpha", "color": _hex(color), "args": [self._number().node]},
        )

    def mix(self, start: str, stop: str) -> Expression:
        """Mix two colours by this number, clamped to 0..1.

        Args:
            start: The colour at 0.
            stop: The colour at 1.

        Returns:
            A colour expression.
        """
        return _node(
            "color",
            {
                "op": "mix",
                "colors": [_hex(start), _hex(stop)],
                "args": [self._number().node],
            },
        )

    def to_wire(self) -> dict[str, Any]:
        """Return the wire object a colour prop carries.

        Returns:
            ``{"type": "expression", "node": ...}``.
        """
        return {"type": "expression", "node": dict(self.node)}

    def _number(self) -> Expression:
        if self.kind != "number":
            raise TypeError("a colour expression has no arithmetic")
        return self


def Stream(key: str, name: str) -> Expression:  # noqa: N802 -- reads as a constructor
    """Read a holder's stream: the node declared with ``key``, each frame.

    Args:
        key: The ``key`` of the component whose state holder exposes the stream.
        name: The stream, one its state family exposes (``STATE_STREAMS``).

    Returns:
        A number expression.

    Raises:
        ValueError: If no state family exposes ``name``.
    """
    if name not in _STREAMS:
        raise ValueError(
            f"no state family exposes a stream {name!r}; streams: {sorted(_STREAMS)}"
        )
    return _node("number", {"stream": key, "name": name})


def _arithmetic(op: str, left: Expression, right: float | Expression) -> Expression:
    other = right._number().node if isinstance(right, Expression) else _literal(right)
    return _node("number", {"op": op, "args": [left._number().node, other]})


def _literal(value: float) -> dict[str, Any]:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"expressions combine numbers, not {type(value).__name__}")
    return {"number": float(value)}


def _hex(color: str) -> str:
    if not isinstance(color, str) or _COLOR.fullmatch(color) is None:
        raise ValueError(
            f"colours in expressions are #RRGGBB or #AARRGGBB, not {color!r}"
        )
    return color


def _node(kind: Kind, node: dict[str, Any]) -> Expression:
    expression = Expression(node, kind)
    validate_expression(expression.to_wire(), kind)
    return expression


def validate_expression(value: object, expected: Kind) -> list[tuple[str, str]]:
    """Check an expression's wire form: closed vocabulary, types and limits.

    Args:
        value: The ``{"type": "expression", ...}`` object.
        expected: The kind the prop needs.

    Returns:
        Each stream the expression reads, as (holder reference, stream name).

    Raises:
        IrValidationError: If the expression is malformed, mistyped or too large.
    """
    if not isinstance(value, Mapping) or set(value) != {"type", "node"}:
        raise IrValidationError("an expression is {type: expression, node}")
    streams: list[tuple[str, str]] = []
    count = [0]
    kind = _kind(value["node"], 1, count, streams)
    if kind != expected:
        raise IrValidationError(
            f"expression gives a {kind}, the prop needs a {expected}"
        )
    return streams


def _kind(
    node: object, depth: int, count: list[int], streams: list[tuple[str, str]]
) -> Kind:
    """The kind one node evaluates to, refusing anything outside the vocabulary."""
    count[0] += 1
    if depth > EXPRESSION_LIMITS["depth"] or count[0] > EXPRESSION_LIMITS["nodes"]:
        raise IrValidationError(f"expression exceeds {EXPRESSION_LIMITS}")
    if not isinstance(node, Mapping):
        raise IrValidationError("an expression node is an object")
    number = node.get("number")
    if (
        set(node) == {"number"}
        and isinstance(number, int | float)
        and not isinstance(number, bool)
    ):
        return "number"
    if set(node) == {"stream", "name"}:
        if not isinstance(node["stream"], str) or node["name"] not in _STREAMS:
            raise IrValidationError(f"unknown stream {node.get('name')!r}")
        streams.append((node["stream"], node["name"]))
        return "number"
    op, args = node.get("op"), node.get("args")
    if op not in EXPRESSION_OPS or not isinstance(args, list | tuple):
        raise IrValidationError(f"unknown expression op {op!r}")
    arity = {"clamp": 3, "alpha": 1, "mix": 1}.get(str(op), 2)
    extra = {"alpha": {"color"}, "mix": {"colors"}}.get(str(op), set())
    if len(args) != arity or set(node) != {"op", "args", *extra}:
        raise IrValidationError(f"expression op {op!r} takes {arity} arguments")
    if any(_kind(arg, depth + 1, count, streams) != "number" for arg in args):
        raise IrValidationError(f"expression op {op!r} takes numbers")
    colors = [node["color"]] if op == "alpha" else list(node.get("colors", ()))
    if op == "mix" and len(colors) != 2:
        raise IrValidationError("mix takes two colours")
    if any(not isinstance(c, str) or _COLOR.fullmatch(c) is None for c in colors):
        raise IrValidationError("expression colours are #RRGGBB or #AARRGGBB")
    return "color" if op in {"alpha", "mix"} else "number"
