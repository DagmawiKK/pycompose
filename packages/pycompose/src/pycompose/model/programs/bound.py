"""Bound arguments: a host function with its last parameters fixed by the app.

The host gives a function's first arguments -- a canvas its size, each frame --
and the app fixes the rest from its state when it describes the screen::

    Canvas(on_draw=gauge.bind(state.level, state.warn))

The wire form is ``{"type": "bound", "program": ..., "args": [...]}``; both
validators check each value against its parameter's type.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from pycompose.errors import IrValidationError
from pycompose.model.nodes.props import JsonValue
from pycompose.model.programs.functions import (
    LONG,
    HostFunction,
    Type,
    validate_function,
)


def bind(function: HostFunction, args: tuple[object, ...]) -> BoundFunction:
    """Fix a host function's last arguments.

    Args:
        function: The host function.
        args: Values for its last parameters, in order.

    Returns:
        The function with those arguments fixed.

    Raises:
        IrValidationError: If there are more values than parameters, or one
            does not have its parameter's type.
    """
    params = function.signature.params
    if len(args) > len(params):
        raise IrValidationError(f"{function.name} takes {len(params)} arguments")
    types = params[len(params) - len(args) :]
    values = tuple(
        _bound_value(function.name, type_, value)
        for type_, value in zip(types, args, strict=True)
    )
    return BoundFunction(function, values)


@dataclass(frozen=True, slots=True)
class BoundFunction:
    """A host function with its last arguments fixed by the app.

    Attributes:
        function: The host function.
        args: The values fixed for its last parameters.
    """

    function: HostFunction
    args: tuple[int | float | bool | str, ...]

    def __call__(self, *args: object) -> object:
        """Run the Python function with the given arguments, then the bound ones.

        Args:
            *args: The arguments the host gives.

        Returns:
            What it returns.
        """
        return self.function(*args, *self.args)

    def to_wire(self) -> dict[str, JsonValue]:
        """Return the bound program's wire form.

        Returns:
            ``{"type": "bound", "program": {...}, "args": [...]}``.
        """
        return {
            "type": "bound",
            "program": self.function.to_wire(),
            "args": list(self.args),
        }


def _bound_value(name: str, type_: Type, value: object) -> int | float | bool | str:
    """One bound argument, as its parameter's type holds it."""
    if not valid_value(type_, value):
        raise IrValidationError(f"{name}'s {type_} parameter cannot take {value!r}")
    if type_ == "string":
        return cast("str", value)
    return float(cast("float", value)) if type_ == "number" else cast("int", value)


def valid_value(type_: Type, value: object) -> bool:
    """Whether a value is one a parameter of the type can be given.

    Args:
        type_: The parameter's type.
        value: The value.

    Returns:
        True for a bool as a boolean, an int within a Long as an integer, a
        finite int or float as a number, and a str as a string.
    """
    if isinstance(value, str) or type_ == "string":
        return isinstance(value, str) and type_ == "string"
    if isinstance(value, bool) or type_ == "boolean":
        return isinstance(value, bool) and type_ == "boolean"
    if type_ == "integer":
        return isinstance(value, int) and -LONG <= value < LONG
    return isinstance(value, int | float) and math.isfinite(value)


def validate_function_call(value: object, head: tuple[str, ...], result: str) -> None:
    """Check what a function prop runs: a value function of the host's arguments.

    The host calls it with ``head`` -- a drawer the anchor it may settle at --
    and needs ``result`` back; a function reading more has the rest bound, as
    ``{"type": "bound", "program": ..., "args": [...]}``.

    Args:
        value: The prop's wire value, its program in place.
        head: The types of the arguments the host gives, in order.
        result: The type the host needs back.

    Raises:
        IrValidationError: If it is no such function, or its bound arguments
            do not fill its remaining parameters with their types.
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
    signature = validate_function(program)
    if signature.params[: len(head)] != head or signature.result != result:
        wanted = f"({', '.join(head)}, ...) -> {result}"
        raise IrValidationError(f"a function {signature} is not {wanted}")
    rest = signature.params[len(head) :]
    if not isinstance(args, list | tuple) or len(args) != len(rest):
        raise IrValidationError(f"a function needs {len(rest)} bound arguments")
    if not all(valid_value(t, a) for t, a in zip(rest, args, strict=True)):
        raise IrValidationError(f"a function's bound arguments are {list(rest)}")
