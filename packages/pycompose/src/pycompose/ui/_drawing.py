"""Compile a ``@host`` draw function: statements that paint, not a value.

A host function that returns ``None`` draws. It takes the canvas's width and
height, as floats, then any arguments the app binds, and its statements
(``_statements``) call the draw calls imported from ``pycompose.ui`` --
``circle``, ``rect`` and the rest, one per draw member the pinned ``DrawScope``
declares -- with a literal default where the pin has one.
"""

from __future__ import annotations

import ast
from functools import cached_property
from typing import Any, cast

from pycompose.model.programs.drawing import draw_kind, draws
from pycompose.model.programs.statements import ProgramKind
from pycompose.ui._compile import Scope
from pycompose.ui._statements import Statement, StatementCompiler


class DrawCompiler(StatementCompiler):
    """Compiles one draw function into a draw program."""

    @cached_property
    def kind(self) -> ProgramKind:  # type: ignore[override]
        return draw_kind()

    def make(self, call: ast.Call, scope: Scope) -> Statement:
        callee = call.func.id if isinstance(call.func, ast.Name) else None
        # A draw call is one imported from pycompose.ui, whatever it is named here.
        name = getattr(self.constants.get(callee or ""), "__draw__", None)
        spec = draws().get(name or "")
        if name is None or spec is None:
            self.refuse(
                call,
                f"{callee or 'that'} is no draw call; import one from pycompose.ui",
            )
        wanted = cast("list[dict[str, Any]]", spec["arguments"])
        return {"call": name, "args": self.arguments(name, call, wanted, scope)}
