"""Compile a ``@host`` draw function: statements that paint, not a value.

A host function that returns ``None`` draws. It takes the canvas's width and
height, as floats, and its body is statements the value functions do not have:

- a draw call imported from ``pycompose.ui`` -- ``circle``, ``rect`` and the
  rest, one per draw member the pinned ``DrawScope`` declares -- with its
  arguments by position or by name, and a literal default where the pin has one;
- ``if``/``else`` blocks of statements;
- ``for i in range(N)`` with a literal ``N``, whose body reads ``i``;
- locals assigned once, as in a value function.

Expressions are a value function's, so ``sin``, ``cos`` and module constants
such as ``pi`` work as they do there.
"""

from __future__ import annotations

import ast
from typing import Any, cast

from pycompose.model.programs.drawing import DRAW, draws, validate_drawing
from pycompose.model.programs.functions import HostFunction, Signature, host_function
from pycompose.ui._compile import Scope, _Compiler, _Term

Statement = dict[str, Any]


class DrawCompiler(_Compiler):
    """Compiles one draw function into a draw program."""

    def run(self) -> HostFunction:
        definition, params = self.signature()
        body = self.statements(self.docless(definition.body), params, 0)
        signature = Signature(tuple(t.type for t in params.values()), DRAW)
        return host_function(
            self.function.__name__,
            signature,
            cast("Any", body),
            self.function,
            validate_drawing,
        )

    def statements(
        self, body: list[ast.stmt], scope: Scope, loops: int
    ) -> list[Statement]:
        compiled: list[Statement] = []
        for index, statement in enumerate(body):
            if isinstance(statement, ast.Assign | ast.AnnAssign):
                name, local = self.local(statement, scope)
                rest = self.statements(body[index + 1 :], {**scope, name: local}, loops)
                return [*compiled, *rest]
            compiled.extend(self.statement(statement, scope, loops))
        return compiled

    def statement(
        self, statement: ast.stmt, scope: Scope, loops: int
    ) -> list[Statement]:
        match statement:
            case ast.Expr(value=ast.Call() as call):
                return [self.draw(call, scope)]
            case ast.If(test=test, body=then, orelse=otherwise):
                return [
                    {
                        "if": self.expression(test, scope).node,
                        "then": self.statements(then, scope, loops),
                        "else": self.statements(otherwise, scope, loops),
                    }
                ]
            case ast.For(
                target=ast.Name(id=name),
                iter=ast.Call(
                    func=ast.Name(id="range"), args=[ast.Constant(value=int() as count)]
                ),
                body=body,
                orelse=[],
            ):
                index = _Term({"loop": loops}, "integer")
                return [
                    {
                        "repeat": count,
                        "body": self.statements(
                            body, {**scope, name: index}, loops + 1
                        ),
                    }
                ]
            case ast.Pass():
                return []
        self.refuse(
            statement,
            f"a draw function cannot use {type(statement).__name__}; it draws, "
            "branches, loops over range(N) and assigns locals",
        )

    def draw(self, call: ast.Call, scope: Scope) -> Statement:
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
        given: dict[str, ast.expr] = {}
        for argument, value in zip(wanted, call.args, strict=False):
            given[argument["name"]] = value
        if len(call.args) > len(wanted):
            self.refuse(call, f"{name} takes {len(wanted)} arguments")
        for keyword in call.keywords:
            camel = _camel(keyword.arg or "")
            if camel not in {argument["name"] for argument in wanted} or camel in given:
                self.refuse(keyword, f"{name} has no argument {keyword.arg!r} to give")
            given[camel] = keyword.value
        args = []
        for argument in wanted:
            if argument["name"] in given:
                term = self.expression(given[argument["name"]], scope)
                term = self.coerce(term, argument["type"], call)
            elif "default" in argument:
                term = self.constant(ast.Constant(argument["default"]), scope)
                term = self.coerce(term, argument["type"], call)
            else:
                missing = [
                    a["name"]
                    for a in wanted
                    if a["name"] not in given and "default" not in a
                ]
                self.refuse(call, f"{name} needs {', '.join(map(_snake, missing))}")
            args.append(term.node)
        return {"draw": name, "args": args}

    def local(
        self, statement: ast.Assign | ast.AnnAssign, scope: Scope
    ) -> tuple[str, _Term]:
        target = (
            statement.targets[0]
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1
            else statement.target
            if isinstance(statement, ast.AnnAssign)
            else None
        )
        if (
            not isinstance(target, ast.Name)
            or statement.value is None
            or target.id in scope
        ):
            self.refuse(statement, "a local is one new name, assigned once")
        return target.id, self.expression(statement.value, scope)


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def _snake(name: str) -> str:
    return "".join(f"_{c.lower()}" if c.isupper() else c for c in name)
