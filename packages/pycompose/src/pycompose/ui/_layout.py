"""Compile a ``@host`` layout function, and the calls a layout makes.

A host function annotated to return ``Size`` lays out. It takes the largest
width and height it may take and how many children it has, then any arguments
the app binds; its statements (``_statements``) read each child's measured
size with ``child_width(i)`` and ``child_height(i)``, place it with
``place(i, x, y)``, may loop over ``range(count)``, and end by returning the
layout's own ``Size(width, height)``.
"""

from __future__ import annotations

import ast

from pycompose.model.programs import recording
from pycompose.model.programs.functions import HostFunction
from pycompose.model.programs.layout import KIND
from pycompose.model.programs.statements import ProgramKind
from pycompose.ui._compile import Scope, _Term
from pycompose.ui._statements import Statement, StatementCompiler

__all__ = ["child_height", "child_width", "place"]

PLACE = [
    {"name": "index", "type": "integer"},
    {"name": "x", "type": "number"},
    {"name": "y", "type": "number"},
]
SIZE = [{"name": "width", "type": "number"}, {"name": "height", "type": "number"}]


def place(index: int, x: float, y: float) -> None:
    """Place one child; call it inside a ``@host`` layout function.

    Args:
        index: The child's index.
        x: Its left edge, in px.
        y: Its top edge, in px.
    """
    recording.place(index, x, y)


def child_width(index: int) -> float:
    """One child's measured width, in px; a child out of range measures 0.

    Args:
        index: The child's index.

    Returns:
        Its width.
    """
    return recording.measured(index)[0]


def child_height(index: int) -> float:
    """One child's measured height, in px; a child out of range measures 0.

    Args:
        index: The child's index.

    Returns:
        Its height.
    """
    return recording.measured(index)[1]


place.__layout__ = "place"  # type: ignore[attr-defined]
child_width.__layout__ = "childWidth"  # type: ignore[attr-defined]
child_height.__layout__ = "childHeight"  # type: ignore[attr-defined]


def is_size(value: object) -> bool:
    """Whether a name or annotation is the catalog's ``Size``, from any slice.

    An app imports values from its own ``components`` package, so the family
    is known by its name rather than one function object.

    Args:
        value: An annotation, or what a name in the function refers to.

    Returns:
        True for ``Size`` or the string ``"Size"``.
    """
    return value == "Size" or getattr(value, "__name__", None) == "Size"


class LayoutCompiler(StatementCompiler):
    """Compiles one layout function into a layout program."""

    kind: ProgramKind = KIND

    def run(self) -> HostFunction:
        definition, _ = self.signature()
        body = self.docless(definition.body)
        final = body[-1] if body else definition
        if not isinstance(final, ast.Return):
            self.refuse(final, "a layout function ends by returning its Size")
        # The body is parsed again to compile, so the last statement is known by place.
        self.final = (final.lineno, final.col_offset)
        return super().run()

    def count(self, node: ast.expr) -> int | str:
        names = list(self.params)
        if isinstance(node, ast.Name) and len(names) > 2 and node.id == names[2]:
            return "children"
        return super().count(node)

    def make(self, call: ast.Call, scope: Scope) -> Statement:
        if self.marker(call) != "place":
            self.refuse(
                call, "a layout calls place(i, x, y); import it from pycompose.ui"
            )
        return {"call": "place", "args": self.arguments("place", call, PLACE, scope)}

    def call(self, node: ast.Call, scope: Scope) -> _Term:
        op = self.marker(node)
        if op not in {"childWidth", "childHeight"}:
            return super().call(node, scope)
        (index,) = self.arguments(
            op, node, [{"name": "index", "type": "integer"}], scope
        )
        return _Term({"op": op, "args": [index]}, "number")

    def other(self, statement: ast.stmt, scope: Scope) -> list[Statement]:
        value = statement.value if isinstance(statement, ast.Return) else None
        if (
            (statement.lineno, statement.col_offset) != self.final
            or not isinstance(value, ast.Call)
            or not isinstance(value.func, ast.Name)
            or not is_size(self.constants.get(value.func.id))
        ):
            return super().other(statement, scope)
        return [{"call": "size", "args": self.arguments("Size", value, SIZE, scope)}]

    def marker(self, call: ast.Call) -> str | None:
        callee = call.func.id if isinstance(call.func, ast.Name) else ""
        return getattr(self.constants.get(callee), "__layout__", None)
