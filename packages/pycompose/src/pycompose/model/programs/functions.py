"""Value functions: Python a parameter calls on the host, checked before it runs.

Some Compose parameters are functions the component calls while it draws:
``SelectableDates.isSelectableDate(utcTimeMillis)`` answers for every day cell a
date picker shows. Python cannot answer within the frame, so the app writes the
function in Python and it crosses as a program the host evaluates::

    @host
    def weekdays(utc_time_millis: int) -> bool:
        return (utc_time_millis // 86_400_000 + 3) % 7 < 5

A program is an expression over its arguments in a closed, total vocabulary
(``FUNCTION_SIGNATURES``) of integers, numbers and booleans. Both validators check its
types and size (``FUNCTION_LIMITS``), so it always answers, in bounded time,
with the type its parameter needs. Integers are 64-bit, as Kotlin's ``Long``.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal, cast

from pycompose.errors import IrValidationError
from pycompose.model.canonical import FrozenJsonValue, freeze_json, thaw_json
from pycompose.model.catalog.vocabulary import FUNCTION_LIMITS, FUNCTION_SIGNATURES
from pycompose.model.nodes.props import JsonValue

Type = Literal["integer", "number", "boolean"]
TYPES: tuple[Type, ...] = ("integer", "number", "boolean")
LONG = 2**63


@dataclass(frozen=True, slots=True)
class Signature:
    """The argument types a function takes and the type it returns.

    Attributes:
        params: Each argument's type, in order.
        result: What it returns.
    """

    params: tuple[Type, ...]
    result: Type

    def __str__(self) -> str:
        """Spell the signature as a reader would.

        Returns:
            ``(integer) -> boolean``, say.
        """
        return f"({', '.join(self.params)}) -> {self.result}"


@dataclass(frozen=True, slots=True)
class HostFunction:
    """A Python function compiled to a program the host calls.

    It still calls as the Python it was written as, so tests can compare the
    two; the host only ever runs the program.

    Attributes:
        name: The Python function's name, for messages.
        signature: Its argument and result types.
        body: The checked program body, frozen.
        function: The Python function itself.
    """

    name: str
    signature: Signature
    body: Mapping[str, FrozenJsonValue]
    function: Callable[..., object] = field(compare=False, repr=False)

    def __call__(self, *args: object) -> object:
        """Run the Python function.

        Args:
            *args: Its arguments.

        Returns:
            What it returns.
        """
        return self.function(*args)

    def to_wire(self) -> dict[str, JsonValue]:
        """Return the program's wire form.

        Returns:
            ``{"type": "program", "params": [...], "result": ..., "body": ...}``.
        """
        return {
            "type": "program",
            "params": list(self.signature.params),
            "result": self.signature.result,
            "body": cast("JsonValue", thaw_json(dict(self.body))),
        }


def host_function(
    name: str,
    signature: Signature,
    body: Mapping[str, JsonValue],
    function: Callable[..., object],
) -> HostFunction:
    """Check a compiled body against its signature and wrap it.

    Args:
        name: The function's name.
        signature: Its argument and result types.
        body: The compiled program body.
        function: The Python function.

    Returns:
        The host function.
    """
    wire = {
        "type": "program",
        "params": list(signature.params),
        "result": signature.result,
        "body": dict(body),
    }
    validate_function(wire)
    frozen = cast("Mapping[str, FrozenJsonValue]", freeze_json(dict(body)))
    return HostFunction(name, signature, frozen, function)


def lower_function(value: object) -> object:
    """A value as wire data: a host function as its program.

    Args:
        value: What the app passed.

    Returns:
        The program's wire form, or ``value`` itself.
    """
    return value.to_wire() if isinstance(value, HostFunction) else value


def validate_function(value: object) -> Signature:
    """Check a program's wire form: closed vocabulary, types and limits.

    Args:
        value: The ``{"type": "program", ...}`` object.

    Returns:
        Its signature, for the caller to match against the parameter's.

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
    params, result = value["params"], value["result"]
    if (
        value["type"] != "program"
        or not isinstance(params, list | tuple)
        or len(params) > FUNCTION_LIMITS["arguments"]
        or any(param not in TYPES for param in params)
        or result not in TYPES
    ):
        raise IrValidationError("a program's params and result are types")
    signature = Signature(tuple(params), cast("Type", result))
    if _Walk(signature.params).type(value["body"], 1) != result:
        raise IrValidationError(f"a program's body does not give a {result}")
    return signature


def result_type(op: str, args: list[Type]) -> Type | None:
    """The type an operation gives over arguments of these types, if any.

    Args:
        op: An operation in ``FUNCTION_SIGNATURES``.
        args: Its arguments' types.

    Returns:
        The result type, or None when the operation does not take them.
    """
    return cast("Type | None", FUNCTION_SIGNATURES[op].get(tuple(args)))


class _Walk:
    """Types one body, counting its nodes against the limits."""

    def __init__(self, params: tuple[Type, ...]) -> None:
        self.params = params
        self.count = 0

    def type(self, node: object, depth: int) -> Type:
        self.count += 1
        if depth > FUNCTION_LIMITS["depth"] or self.count > FUNCTION_LIMITS["nodes"]:
            raise IrValidationError(f"program exceeds {FUNCTION_LIMITS}")
        if not isinstance(node, Mapping) or not node:
            raise IrValidationError("a program node is an object")
        if len(node) == 1:
            ((key, literal),) = node.items()
            return self.leaf(str(key), literal)
        op, args = node.get("op"), node.get("args")
        signatures = FUNCTION_SIGNATURES.get(str(op), {})
        if (
            set(node) != {"op", "args"}
            or not signatures
            or not isinstance(args, list | tuple)
            or len(args) != len(next(iter(signatures)))
        ):
            raise IrValidationError(f"unknown program op {op!r}")
        given = [self.type(arg, depth + 1) for arg in args]
        typed = result_type(str(op), given)
        if typed is None:
            raise IrValidationError(f"program op {op!r} does not take {given}")
        return typed

    def leaf(self, key: str, literal: object) -> Type:
        if isinstance(literal, bool):
            if key == "boolean":
                return "boolean"
        elif isinstance(literal, int):
            if key == "integer" and -LONG <= literal < LONG:
                return "integer"
            if key == "arg" and 0 <= literal < len(self.params):
                return self.params[literal]
            if key == "number":
                return "number"
        elif isinstance(literal, float) and key == "number" and math.isfinite(literal):
            return "number"
        raise IrValidationError(f"unknown program leaf {key!r}")
