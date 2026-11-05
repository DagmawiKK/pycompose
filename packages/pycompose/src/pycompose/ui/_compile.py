"""Compile a ``@host`` Python function to a program the host evaluates.

The function is read from its source, once, as it is defined. What it may say
is a small, total part of Python over ``int``, ``float`` and ``bool``:

- arguments, locals assigned once, and ``int``/``float``/``bool`` constants
  the module or enclosing function defines (read as the function is defined);
- arithmetic (``+ - * / // %``), comparisons (chained too), ``and``, ``or``,
  ``not``, ``x if c else y``, and ``abs``, ``min``, ``max`` (two arguments),
  ``float``, and ``sin`` and ``cos`` (from ``math``);
- ``if`` blocks that return, and a final ``return``.

Integers mix with floats as Python mixes them. Two things differ on the host:
integers are 64-bit, and ``x // 0`` and ``x % 0`` give 0 rather than raising.
Anything else -- loops, calls, attributes, strings, I/O -- is refused with the
line that says it.
"""

from __future__ import annotations

import ast
import inspect
import math
import textwrap
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import FunctionType
from typing import Any, NoReturn, cast

from pycompose.model.programs.functions import (
    HostFunction,
    Signature,
    Type,
    host_function,
    result_type,
)
from pycompose.ui._sources import built_source

ANNOTATIONS: dict[str, Type] = {"int": "integer", "float": "number", "bool": "boolean"}
BINARY = {
    ast.Add: "plus",
    ast.Sub: "minus",
    ast.Mult: "times",
    ast.Div: "div",
    ast.FloorDiv: "floorDiv",
    ast.Mod: "mod",
}
COMPARE = {
    ast.Lt: "lt",
    ast.LtE: "le",
    ast.Gt: "gt",
    ast.GtE: "ge",
    ast.Eq: "eq",
    ast.NotEq: "ne",
}

CALLS = {"float", "abs", "min", "max", "sin", "cos"}

Node = dict[str, Any]


@dataclass(frozen=True, slots=True)
class _Term:
    node: Node
    type: Type


Scope = dict[str, _Term]


def compile_function(function: Callable[..., object]) -> HostFunction:
    """Compile one Python function, refusing what the language cannot say.

    Args:
        function: A function annotated with ``int``, ``float`` and ``bool``.

    Returns:
        The host function: the program, still callable as Python.
    """
    return _Compiler(function).run()


class _Compiler:
    def __init__(self, function: Callable[..., object]) -> None:
        self.function = function
        self.file = inspect.getsourcefile(function) or "<host>"
        self.first = function.__code__.co_firstlineno
        captured = inspect.getclosurevars(function)
        self.constants: Mapping[str, object] = {
            **captured.globals,
            **captured.nonlocals,
        }

    def run(self) -> HostFunction:
        definition, params = self.signature()
        result = self.annotation(definition.returns, definition)
        body = self.docless(definition.body)
        term = self.block(body, params, definition, result)
        signature = Signature(tuple(t.type for t in params.values()), result)
        return host_function(
            self.function.__name__, signature, term.node, self.function
        )

    def signature(self) -> tuple[ast.FunctionDef, Scope]:
        """The definition, checked against the code it compiled to, and its params."""
        try:
            source = inspect.getsource(self.function)
        except OSError:
            # An app on a device ships bytecode; the build kept this source.
            self.file, source = built_source(cast("FunctionType", self.function))
        definition = ast.parse(textwrap.dedent(source)).body[0]
        if not isinstance(definition, ast.FunctionDef):
            self.refuse(definition, "a host function is a plain def")
        arguments = definition.args
        code = self.function.__code__
        if definition.name != self.function.__name__ or [
            argument.arg for argument in arguments.args
        ] != list(code.co_varnames[: code.co_argcount]):
            self.refuse(definition, "its source is not its code's; rebuild the app")
        if (
            arguments.posonlyargs
            or arguments.vararg
            or arguments.kwonlyargs
            or arguments.kwarg
            or arguments.defaults
        ):
            self.refuse(definition, "a host function takes plain arguments only")
        params = {
            argument.arg: _Term({"arg": index}, self.annotation(argument.annotation))
            for index, argument in enumerate(arguments.args)
        }
        return definition, params

    @staticmethod
    def docless(body: list[ast.stmt]) -> list[ast.stmt]:
        """A body without its docstring."""
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
        ):
            return body[1:]
        return body

    def annotation(self, node: ast.expr | None, where: ast.AST | None = None) -> Type:
        name = node.id if isinstance(node, ast.Name) else None
        if node is not None and isinstance(node, ast.Constant):
            name = str(node.value)
        if name not in ANNOTATIONS:
            self.refuse(node or where, "annotate with int, float or bool")
        return ANNOTATIONS[name]

    def block(
        self, body: list[ast.stmt], scope: Scope, at: ast.AST, result: Type
    ) -> _Term:
        if not body:
            self.refuse(at, "a host function returns on every path")
        statement, rest = body[0], body[1:]
        if isinstance(statement, ast.Return) and statement.value is not None:
            if rest:
                self.refuse(rest[0], "nothing runs after a return")
            returned = self.expression(statement.value, scope)
            return self.coerce(returned, result, statement)
        if isinstance(statement, ast.Assign | ast.AnnAssign):
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
            local = self.expression(statement.value, scope)
            return self.block(rest, {**scope, target.id: local}, statement, result)
        if isinstance(statement, ast.If):
            then = self.block(statement.body, scope, statement, result)
            otherwise = self.block([*statement.orelse, *rest], scope, statement, result)
            return self.choose(
                self.expression(statement.test, scope), then, otherwise, statement
            )
        self.refuse(statement, f"host functions cannot use {type(statement).__name__}")

    def expression(self, node: ast.expr, scope: Scope) -> _Term:
        handlers: dict[type, Callable[[Any, Scope], _Term]] = {
            ast.Constant: self.constant,
            ast.Name: self.name,
            ast.UnaryOp: self.unary,
            ast.BinOp: self.binary,
            ast.BoolOp: self.boolean,
            ast.Compare: self.compare,
            ast.IfExp: self.conditional,
            ast.Call: self.call,
        }
        handler = handlers.get(type(node))
        if handler is None:
            self.refuse(node, f"host functions cannot use {type(node).__name__}")
        return handler(node, scope)

    def constant(self, node: ast.Constant, _scope: Scope) -> _Term:
        value = node.value
        if isinstance(value, bool):
            return _Term({"boolean": value}, "boolean")
        if isinstance(value, int):
            return _Term({"integer": value}, "integer")
        if isinstance(value, float):
            return _Term({"number": value}, "number")
        self.refuse(node, f"host functions cannot use {type(value).__name__} values")

    def name(self, node: ast.Name, scope: Scope) -> _Term:
        if node.id in scope:
            return scope[node.id]
        value = self.constants.get(node.id)
        if isinstance(value, int | float):
            return self.constant(ast.copy_location(ast.Constant(value), node), scope)
        self.refuse(
            node, f"{node.id!r} is not an argument, a local or a number constant"
        )

    def unary(self, node: ast.UnaryOp, scope: Scope) -> _Term:
        operand = node.operand
        if isinstance(node.op, ast.USub) and isinstance(operand, ast.Constant):
            # A negative literal is a literal, not a negation.
            folded = ast.copy_location(ast.Constant(-operand.value), node)
            return self.constant(folded, scope)
        if isinstance(node.op, ast.Invert):
            self.refuse(node, "host functions cannot use ~")
        term = self.expression(operand, scope)
        if isinstance(node.op, ast.UAdd):
            return term
        return self.apply(
            "neg" if isinstance(node.op, ast.USub) else "not", [term], node
        )

    def binary(self, node: ast.BinOp, scope: Scope) -> _Term:
        if type(node.op) not in BINARY:
            self.refuse(node, f"host functions cannot use {type(node.op).__name__}")
        terms = [self.expression(node.left, scope), self.expression(node.right, scope)]
        return self.arithmetic(BINARY[type(node.op)], terms, node)

    def boolean(self, node: ast.BoolOp, scope: Scope) -> _Term:
        name = "and" if isinstance(node.op, ast.And) else "or"
        terms = [self.expression(value, scope) for value in node.values]
        folded = terms[0]
        for term in terms[1:]:
            folded = self.apply(name, [folded, term], node)
        return folded

    def compare(self, node: ast.Compare, scope: Scope) -> _Term:
        operands = [self.expression(node.left, scope)]
        operands += [self.expression(c, scope) for c in node.comparators]
        result: _Term | None = None
        for op, low, high in zip(node.ops, operands, operands[1:], strict=False):
            if type(op) not in COMPARE:
                self.refuse(
                    node, f"host functions cannot compare with {type(op).__name__}"
                )
            term = self.arithmetic(COMPARE[type(op)], [low, high], node)
            result = term if result is None else self.apply("and", [result, term], node)
        return cast("_Term", result)

    def conditional(self, node: ast.IfExp, scope: Scope) -> _Term:
        return self.choose(
            self.expression(node.test, scope),
            self.expression(node.body, scope),
            self.expression(node.orelse, scope),
            node,
        )

    def call(self, node: ast.Call, scope: Scope) -> _Term:
        name = node.func.id if isinstance(node.func, ast.Name) else None
        if name not in CALLS or node.keywords:
            self.refuse(node, f"host functions cannot call {name or 'that'}")
        terms = [self.expression(a, scope) for a in node.args]
        if name in {"sin", "cos"} and self.constants.get(name) is not getattr(
            math, name
        ):
            self.refuse(node, f"{name} must be math.{name}")
        if name in {"sin", "cos"} and len(terms) == 1:
            return self.apply(name, [self.coerce(terms[0], "number", node)], node)
        if name == "float" and len(terms) == 1:
            return self.coerce(terms[0], "number", node)
        if name == "abs" and len(terms) == 1:
            zero = _Term({"integer": 0}, "integer")
            negative = self.arithmetic("lt", [terms[0], zero], node)
            return self.choose(negative, self.apply("neg", terms, node), terms[0], node)
        if name in {"min", "max"} and len(terms) == 2:
            low, high = self.promoted(terms)
            first = self.apply("le" if name == "min" else "ge", [low, high], node)
            return self.choose(first, low, high, node)
        self.refuse(
            node, f"{name} takes {'two arguments' if name in {'min', 'max'} else 'one'}"
        )

    def arithmetic(self, op: str, terms: list[_Term], node: ast.expr) -> _Term:
        # Python promotes an integer meeting a float, and divides to a float.
        promoted = self.promoted(terms)
        if op == "div":
            promoted = [self.coerce(t, "number", node) for t in promoted]
        return self.apply(op, promoted, node)

    def promoted(self, terms: list[_Term]) -> list[_Term]:
        if {t.type for t in terms} == {"integer", "number"}:
            return [self.coerce(t, "number", None) for t in terms]
        return terms

    def coerce(self, term: _Term, wanted: Type, node: ast.AST | None) -> _Term:
        if term.type == wanted:
            return term
        if term.type == "integer" and wanted == "number":
            if "integer" in term.node:
                return _Term({"number": float(term.node["integer"])}, "number")
            return _Term({"op": "toNumber", "args": [term.node]}, "number")
        article = "an" if term.type == "integer" else "a"
        self.refuse(node, f"gives {article} {term.type} where a {wanted} is needed")

    def choose(
        self, test: _Term, then: _Term, otherwise: _Term, node: ast.AST
    ) -> _Term:
        then, otherwise = self.promoted([then, otherwise])
        return self.apply("if", [test, then, otherwise], node)

    def apply(self, op: str, terms: list[_Term], node: ast.AST) -> _Term:
        typed = result_type(op, [t.type for t in terms])
        if typed is None:
            given = ", ".join(t.type for t in terms)
            self.refuse(node, f"{op} does not take ({given})")
        return _Term({"op": op, "args": [t.node for t in terms]}, cast("Type", typed))

    def refuse(self, node: ast.AST | None, message: str) -> NoReturn:
        line = self.first + getattr(node, "lineno", 1) - 1
        raise SyntaxError(
            f"{self.function.__qualname__}: {message}",
            (self.file, line, getattr(node, "col_offset", 0) + 1, None),
        )
