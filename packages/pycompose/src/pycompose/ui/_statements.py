"""Compile a ``@host`` statement function: one that paints or places, not a value.

Draw and layout functions share their statements (``model/programs/statements``):

- a call the program kind knows, by position or by name;
- ``if``/``else`` blocks of statements;
- ``for i in range(N)`` with a literal ``N``, whose body reads ``i``, and in a
  layout ``for i in range(count)`` over the children it lays out;
- locals, assigned and reassigned with one type; a local opened in a block
  closes with it.

Expressions are a value function's, so ``sin``, ``cos`` and module constants
such as ``pi`` work as they do there.
"""

from __future__ import annotations

import ast
from typing import Any

from pycompose.model.programs.functions import HostFunction, Signature, host_function
from pycompose.model.programs.statements import ProgramKind, validate_statements
from pycompose.ui._compile import Scope, _Compiler, _Term

Statement = dict[str, Any]


class StatementCompiler(_Compiler):
    """Compiles one statement function into a program of its kind."""

    kind: ProgramKind

    def run(self) -> HostFunction:
        definition, params = self.signature()
        self.params = params
        self.open = 0
        body = self.statements(self.docless(definition.body), params, 0)
        signature = Signature(tuple(t.type for t in params.values()), self.kind.result)
        return host_function(
            self.function.__name__,
            signature,
            body,  # type: ignore[arg-type]
            self.function,
            lambda value: validate_statements(value, self.kind),
        )

    def statements(
        self, body: list[ast.stmt], scope: Scope, loops: int
    ) -> list[Statement]:
        scope = dict(scope)
        opened = self.open
        compiled: list[Statement] = []
        for statement in body:
            if isinstance(statement, ast.Assign | ast.AnnAssign):
                compiled.append(self.assign(statement, scope))
            else:
                compiled.extend(self.statement(statement, scope, loops))
        self.open = opened
        return compiled

    def statement(
        self, statement: ast.stmt, scope: Scope, loops: int
    ) -> list[Statement]:
        match statement:
            case ast.Expr(value=ast.Call() as call):
                return [self.make(call, scope)]
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
                iter=ast.Call(func=ast.Name(id="range"), args=[count]),
                body=body,
                orelse=[],
            ):
                index = _Term({"loop": loops}, "integer")
                return [
                    {
                        "repeat": self.count(count),
                        "body": self.statements(
                            body, {**scope, name: index}, loops + 1
                        ),
                    }
                ]
            case ast.Pass():
                return []
        return self.other(statement, scope)

    def count(self, node: ast.expr) -> int | str:
        """A loop's count: a literal, or where the kind has them, its children."""
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        self.refuse(node, "a loop runs range(N) with a literal N")

    def other(self, statement: ast.stmt, scope: Scope) -> list[Statement]:  # noqa: ARG002 -- a kind's statement reads it
        """A statement only some kinds have; refused here."""
        self.refuse(
            statement,
            f"a {self.kind.result} function cannot use {type(statement).__name__}; "
            "it calls, branches, loops over range(N) and assigns locals",
        )

    def make(self, call: ast.Call, scope: Scope) -> Statement:
        """A call statement; each kind names the calls it knows."""
        raise NotImplementedError

    def arguments(
        self,
        name: str,
        call: ast.Call,
        wanted: list[dict[str, Any]],
        scope: Scope,
    ) -> list[Any]:
        """A call's arguments in order, by position or keyword, defaults filled."""
        given: dict[str, ast.expr] = {}
        if len(call.args) > len(wanted):
            self.refuse(call, f"{name} takes {len(wanted)} arguments")
        for argument, value in zip(wanted, call.args, strict=False):
            given[argument["name"]] = value
        for keyword in call.keywords:
            camel = _camel(keyword.arg or "")
            if camel not in {argument["name"] for argument in wanted} or camel in given:
                self.refuse(keyword, f"{name} has no argument {keyword.arg!r} to give")
            given[camel] = keyword.value
        missing = [
            a["name"] for a in wanted if a["name"] not in given and "default" not in a
        ]
        if missing:
            self.refuse(call, f"{name} needs {', '.join(map(_snake, missing))}")
        args = []
        for argument in wanted:
            source = given.get(argument["name"])
            term = (
                self.expression(source, scope)
                if source is not None
                else self.constant(ast.Constant(argument["default"]), scope)
            )
            args.append(self.coerce(term, argument["type"], call).node)
        return args

    def assign(self, statement: ast.Assign | ast.AnnAssign, scope: Scope) -> Statement:
        target = (
            statement.targets[0]
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1
            else statement.target
            if isinstance(statement, ast.AnnAssign)
            else None
        )
        if not isinstance(target, ast.Name) or statement.value is None:
            self.refuse(statement, "a local is one name, assigned a value")
        value = self.expression(statement.value, scope)
        held = scope.get(target.id)
        if held is None:
            scope[target.id] = _Term({"local": self.open}, value.type)
            self.open += 1
            return {"let": value.node}
        if "local" not in held.node:
            self.refuse(statement, f"{target.id} is an argument or a loop's index")
        value = self.coerce(value, held.type, statement)
        return {"set": held.node["local"], "value": value.node}


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def _snake(name: str) -> str:
    return "".join(f"_{c.lower()}" if c.isupper() else c for c in name)
