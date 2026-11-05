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
from typing import TYPE_CHECKING, Literal, cast

from pycompose.errors import IrValidationError
from pycompose.model.canonical import FrozenJsonValue, freeze_json, thaw_json
from pycompose.model.catalog.vocabulary import FUNCTION_LIMITS, FUNCTION_SIGNATURES
from pycompose.model.nodes.props import JsonValue

if TYPE_CHECKING:
    from pycompose.model.programs.bound import BoundFunction

Type = Literal["integer", "number", "boolean"]
Result = Literal["integer", "number", "boolean", "draw", "layout"]
"""What a program gives: a value of a type, or the paint or placement it makes."""
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
    result: Result

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
    body: FrozenJsonValue
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
            "body": cast("JsonValue", thaw_json(self.body)),
        }

    def bind(self, *args: object) -> BoundFunction:
        """Fix the function's last arguments; the host gives the first.

        A canvas gives a draw function its size each frame, so whatever else
        it reads -- a value from the app's state, say -- is bound here::

            Canvas(on_draw=gauge.bind(state.level))

        Args:
            *args: Values for its last parameters, in order.

        Returns:
            The function with those arguments fixed.
        """
        # bound.py builds on this module, so it is imported where it is used.
        from pycompose.model.programs.bound import bind

        return bind(self, args)


def host_function(
    name: str,
    signature: Signature,
    body: JsonValue,
    function: Callable[..., object],
    check: Callable[[object], Signature] | None = None,
) -> HostFunction:
    """Check a compiled body against its signature and wrap it.

    Args:
        name: The function's name.
        signature: Its argument and result types.
        body: The compiled program body.
        function: The Python function.
        check: The checker for its kind; a value function's by default.

    Returns:
        The host function.
    """
    wire = {
        "type": "program",
        "params": list(signature.params),
        "result": signature.result,
        "body": body,
    }
    (check or validate_function)(wire)
    return HostFunction(name, signature, freeze_json(body), function)


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
    if Walk(signature.params).type(value["body"], 1) != result:
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


class Walk:
    """Types one program's expressions, counting their nodes against a limit.

    ``loops`` is how many loops enclose the expression being typed; a loop's
    index is an integer leaf, ``{"loop": k}`` for the k-th outermost. ``locals``
    holds the type of each local open there, read as ``{"local": k}``.
    """

    def __init__(
        self,
        params: tuple[Type, ...],
        nodes: int = FUNCTION_LIMITS["nodes"],
        ops: Mapping[str, Mapping[tuple[Type, ...], Type]] | None = None,
    ) -> None:
        """Start a walk.

        Args:
            params: The program's argument types.
            nodes: How many nodes the whole program may hold.
            ops: Operations a program kind adds to the catalog's, by signature.
        """
        self.params = params
        self.nodes = nodes
        self.ops = ops or {}
        self.loops = 0
        self.locals: list[Type] = []
        self.count = 0

    def type(self, node: object, depth: int) -> Type:
        """The type one expression node gives.

        Args:
            node: The node.
            depth: How deeply it nests.

        Returns:
            Its type.

        Raises:
            IrValidationError: If it is outside the vocabulary or the limits.
        """
        self.count += 1
        if depth > FUNCTION_LIMITS["depth"] or self.count > self.nodes:
            raise IrValidationError(f"program exceeds {FUNCTION_LIMITS}")
        if not isinstance(node, Mapping) or not node:
            raise IrValidationError("a program node is an object")
        if len(node) == 1:
            ((key, literal),) = node.items()
            return self.leaf(str(key), literal)
        op, args = node.get("op"), node.get("args")
        signatures = FUNCTION_SIGNATURES.get(str(op)) or self.ops.get(str(op), {})
        if (
            set(node) != {"op", "args"}
            or not signatures
            or not isinstance(args, list | tuple)
            or len(args) != len(next(iter(signatures)))
        ):
            raise IrValidationError(f"unknown program op {op!r}")
        given = [self.type(arg, depth + 1) for arg in args]
        typed = cast("Type | None", signatures.get(tuple(given)))
        if typed is None:
            raise IrValidationError(f"program op {op!r} does not take {given}")
        return typed

    def leaf(self, key: str, literal: object) -> Type:
        """The type one leaf gives: a literal, an argument, a loop's index or a local.

        Args:
            key: The leaf's kind.
            literal: Its value.

        Returns:
            Its type.

        Raises:
            IrValidationError: If the leaf is no known kind or out of range.
        """
        if isinstance(literal, bool):
            if key == "boolean":
                return "boolean"
        elif isinstance(literal, int):
            if key == "integer" and -LONG <= literal < LONG:
                return "integer"
            slots = {"arg": self.params, "local": self.locals}
            slots["loop"] = ["integer"] * self.loops
            if key in slots and 0 <= literal < len(slots[key]):
                return cast("Type", slots[key][literal])
            if key == "number":
                return "number"
        elif isinstance(literal, float) and key == "number" and math.isfinite(literal):
            return "number"
        raise IrValidationError(f"unknown program leaf {key!r}")
