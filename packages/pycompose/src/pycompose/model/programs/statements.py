"""Statement programs: drawings and layouts, run by the host within a frame.

A draw function paints and a layout function places; both are statements
rather than one expression. One checker serves both, and each program kind
names the calls its statements make, any operations its expressions add, and
its limits:

- ``{"call": name, "args": [...]}`` makes one of the kind's calls;
- ``{"if": test, "then": [...], "else": [...]}`` branches;
- ``{"repeat": N, "body": [...]}`` runs a literal count, and
  ``{"repeat": "children", ...}`` once per child where the kind has children;
  the body reads its index as ``{"loop": k}``, k-th from the outermost;
- ``{"let": expr}`` opens a local, read as ``{"local": k}`` in the order the
  enclosing blocks opened them, and ``{"set": k, "value": expr}`` changes it,
  keeping its type. A local closes with the block that opened it.

Every loop is bounded by a literal or by the children the host lays out, so a
frame always ends; a kind may also bound the calls one frame can make, counted
through its loops. Expressions are the value functions' (``functions.py``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from pycompose.errors import IrValidationError
from pycompose.model.catalog.vocabulary import FUNCTION_LIMITS
from pycompose.model.programs.bound import valid_value
from pycompose.model.programs.functions import TYPES, Result, Signature, Type, Walk


@dataclass(frozen=True)
class ProgramKind:
    """What one kind of statement program may do.

    Attributes:
        result: The program's ``result``: ``draw`` or ``layout``.
        head: The arguments the host gives, before any the app binds.
        calls: Each call's argument types.
        limits: ``nodes`` in all, the largest ``repeat`` count, how deeply
            ``loops`` nest, and optionally the ``calls`` one frame may make.
        ops: Operations the kind's expressions add to the catalog's.
        children: Whether a loop may run once per child.
    """

    result: Result
    head: tuple[Type, ...]
    calls: Mapping[str, tuple[Type, ...]]
    limits: Mapping[str, int]
    ops: Mapping[str, Mapping[tuple[Type, ...], Type]] = field(default_factory=dict)
    children: bool = False


def validate_statements(value: object, kind: ProgramKind) -> Signature:
    """Check a statement program's wire form: statements, types and limits.

    Args:
        value: The ``{"type": "program", ...}`` object.
        kind: What the program may do.

    Returns:
        Its signature: the host's arguments, then any the app binds.

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
        or value["result"] != kind.result
        or not isinstance(params, list | tuple)
        or tuple(params[: len(kind.head)]) != kind.head
        or len(params) > FUNCTION_LIMITS["arguments"]
        or any(param not in TYPES for param in params)
    ):
        raise IrValidationError(
            f"a {kind.result} program takes {list(kind.head)}, then types"
        )
    signature = Signature(cast("tuple[Type, ...]", tuple(params)), kind.result)
    _Check(signature.params, kind).block(value["body"], 1)
    return signature


def validate_call(value: object, kind: ProgramKind) -> None:
    """Check what a prop runs: a program of the host's arguments, or one bound.

    A program that reads more than the host gives has the rest bound, as
    ``{"type": "bound", "program": ..., "args": [...]}``.

    Args:
        value: The prop's wire value, its program in place.
        kind: What the program may do.

    Raises:
        IrValidationError: If it is no such program, or its bound arguments do
            not fill its remaining parameters with their types.
    """
    bound = isinstance(value, Mapping) and value.get("type") == "bound"
    if bound and set(cast("Mapping[str, object]", value)) != {
        "type",
        "program",
        "args",
    }:
        raise IrValidationError("a bound program is {type: bound, program, args}")
    program = cast("Mapping[str, object]", value)["program"] if bound else value
    args = cast("Mapping[str, object]", value)["args"] if bound else []
    rest = validate_statements(program, kind).params[len(kind.head) :]
    if not isinstance(args, list | tuple) or len(args) != len(rest):
        raise IrValidationError(f"a {kind.result} needs {len(rest)} bound arguments")
    if not all(valid_value(t, a) for t, a in zip(rest, args, strict=True)):
        raise IrValidationError(f"a {kind.result}'s bound arguments are {list(rest)}")


class _Check:
    """Checks one body, bounding the calls a frame can make where the kind does."""

    def __init__(self, params: tuple[Type, ...], kind: ProgramKind) -> None:
        self.kind = kind
        self.expressions = Walk(params, kind.limits["nodes"], kind.ops)
        self.calls = 0

    def block(self, statements: object, times: int) -> None:
        if not isinstance(statements, list | tuple):
            raise IrValidationError("a program's body is a list of statements")
        opened = len(self.expressions.locals)
        for statement in statements:
            self.statement(statement, times)
        del self.expressions.locals[opened:]

    def statement(self, node: object, times: int) -> None:
        if not isinstance(node, Mapping):
            raise IrValidationError("a statement is an object")
        keys = set(node)
        if keys == {"call", "args"}:
            self.call(node, times)
        elif keys == {"if", "then", "else"}:
            self.expect(node["if"], "boolean", "an if's test")
            self.block(node["then"], times)
            self.block(node["else"], times)
        elif keys == {"repeat", "body"}:
            self.repeat(node, times)
        elif keys == {"let"}:
            self.expressions.locals.append(self.expressions.type(node["let"], 1))
        elif keys == {"set", "value"}:
            slot = node["set"]
            if type(slot) is not int or not 0 <= slot < len(self.expressions.locals):
                raise IrValidationError(f"no local {slot!r} to set")
            self.expect(node["value"], self.expressions.locals[slot], "a local")
        else:
            raise IrValidationError(f"unknown statement {sorted(keys)}")

    def call(self, node: Mapping[str, object], times: int) -> None:
        name, args = node["call"], node["args"]
        wanted = self.kind.calls.get(str(name))
        if wanted is None or not isinstance(args, list | tuple):
            raise IrValidationError(f"unknown {self.kind.result} call {name!r}")
        if len(args) != len(wanted):
            raise IrValidationError(f"{name} takes {len(wanted)} arguments")
        for index, (arg, type_) in enumerate(zip(args, wanted, strict=True)):
            self.expect(arg, type_, f"{name} argument {index}")
        self.calls += times
        budget = self.kind.limits.get("calls")
        if budget is not None and self.calls > budget:
            raise IrValidationError(f"a frame could make more calls than {budget}")

    def repeat(self, node: Mapping[str, object], times: int) -> None:
        count = node["repeat"]
        limits = self.kind.limits
        literal = type(count) is int and 0 <= count <= limits["repeat"]
        children = count == "children" and self.kind.children
        if not (literal or children) or self.expressions.loops >= limits["loops"]:
            raise IrValidationError(f"a loop runs a literal count within {limits}")
        self.expressions.loops += 1
        self.block(node["body"], times * count if literal else times)  # type: ignore[operator]
        self.expressions.loops -= 1

    def expect(self, node: object, wanted: Type, what: str) -> None:
        given = self.expressions.type(node, 1)
        if given != wanted:
            raise IrValidationError(f"{what} takes a {wanted}, not a {given}")
