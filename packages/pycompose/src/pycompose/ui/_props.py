"""What one prop or modifier argument must be, checked as a screen is described.

The rules a value obeys: its type, the family a value-typed prop names, the
bounds a number keeps, and the two forms the host reads on its own -- a binding
and an expression. The node walk that applies them lives in :mod:`._rules`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import cast

from pycompose.errors import IrValidationError
from pycompose.model.canonical import check_json
from pycompose.model.catalog.lock import REGISTRY
from pycompose.model.catalog.registry import PropDef
from pycompose.model.nodes.resources import valid_resource
from pycompose.model.nodes.values import (
    validate_bounds,
    validate_number,
    validate_value,
)
from pycompose.model.programs.bindings import check_binding, is_binding
from pycompose.model.programs.bound import validate_function_call
from pycompose.model.programs.drawing import validate_canvas
from pycompose.model.programs.expressions import (
    EXPRESSION_KINDS,
    is_expression,
    validate_expression,
)
from pycompose.model.programs.layout import validate_placement
from pycompose.ui._bound import binding_refusal
from pycompose.ui.intents import BoundIntent, valid_intent

_LONG = range(-(2**63), 2**63)
"""The integers a host can hold: a Kotlin Long."""


def _is_long(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value in _LONG


def _runs(check: Callable[[object], None], value: object) -> bool:
    # A program of the host's arguments, or one with the rest of them bound.
    try:
        check(value)
    except IrValidationError:
        return False
    return True


_TYPE_CHECKS: dict[str, Callable[[object, PropDef], bool]] = {
    "string": lambda value, _: isinstance(value, str),
    "resource": lambda value, prop: valid_resource(value, prop.values),
    # A colour of a value family crosses the wire only as its tagged object.
    "color": lambda value, prop: isinstance(value, str) and prop.value_type is None,
    "boolean": lambda value, _: isinstance(value, bool),
    "integer": lambda value, _: _is_long(value),
    "durationMs": lambda value, _: _is_long(value),
    "number": lambda value, _: isinstance(value, int | float)
    and not isinstance(value, bool),
    "dp": lambda value, _: _is_native_float(value),
    "modifier": lambda value, _: isinstance(value, Mapping),
    "draw": lambda value, _: _runs(validate_canvas, value),
    "layout": lambda value, _: _runs(validate_placement, value),
    "function": lambda value, prop: _runs(
        lambda wire: validate_function_call(
            wire, tuple(kind for _, kind in prop.payload), str(prop.result)
        ),
        value,
    ),
    # A named constant of a value family crosses the wire only tagged.
    "enum": lambda value, prop: isinstance(value, str)
    and prop.value_type is None
    and value in prop.values,
    "actionId": lambda value, _: isinstance(value, BoundIntent)
    or (isinstance(value, str) and value in REGISTRY.actions),
}
"""How each registered prop type checks a plain value."""


Intents = Mapping[str, Mapping[str, PropDef]]
"""Each stated handler's payload contract, by handler id."""


def validate_prop(
    value: object, prop: PropDef, *, intents: Intents | None = None
) -> bool:
    """Check a JSON value against a generated prop or payload definition.

    Args:
        value: Candidate value, including frozen JSON containers.
        prop: Definition from the component registry.
        intents: The snapshot's intent contracts, for action props.

    Returns:
        Whether the type, bounds and registry references are valid.
    """
    if value is None:
        return prop.nullable
    bound = _validate_bound(value, prop)
    if bound is not None:
        return bound
    if is_expression(value):
        return _validate_expression(value, prop)
    return _valid_plain(value, prop, intents)


def _valid_plain(value: object, prop: PropDef, intents: Intents | None) -> bool:
    """Check a value that is neither absent nor a binding nor an expression.

    Args:
        value: The candidate value.
        prop: Definition of the prop it would fill.
        intents: The snapshot's intent contracts, for action props.

    Returns:
        Whether the type, bounds and registry references are valid.
    """
    check = _TYPE_CHECKS.get(prop.type)
    if isinstance(value, Mapping) and (
        prop.value_type is not None or prop.type == "actionId"
    ):
        # An action prop's object is an intent; any other object is a value.
        return (
            valid_intent(value, intents or {})
            if prop.type == "actionId"
            else _valid_value(value, prop)
        )
    if check is None or not check(value, prop):
        return False
    try:
        if prop.type == "modifier":
            validate_modifier(value, intents=intents)
        else:
            check_json(value)
    except IrValidationError:
        return False
    return not isinstance(value, int | float) or (
        (prop.minimum is None or value >= prop.minimum)
        and (prop.maximum is None or value <= prop.maximum)
    )


def _validate_expression(value: object, prop: PropDef) -> bool:
    """Check an expression filling a prop: it must give the kind its type holds.

    A live expression has no value to check against the prop's bounds, so the
    host enforces those when it reads one. A dp prop carrying another value
    family (PaddingValues) holds a compound value, which a number is not.

    Args:
        value: The ``{"type": "expression", ...}`` object.
        prop: Definition of the prop it would fill.

    Returns:
        Whether the expression is well-formed and of the kind the prop holds.
    """
    kind = EXPRESSION_KINDS.get(prop.type)
    if kind is None:
        return False
    if prop.type == "dp" and prop.value_type not in {None, "Dp"}:
        # A dp prop carrying another family (PaddingValues) holds a compound
        # value, which a number is not.
        return False
    try:
        validate_expression(value, kind)
    except IrValidationError:
        return False
    return True


def _validate_bound(value: object, prop: PropDef) -> bool | None:
    """Check a binding filling a prop, or report that the value is not one.

    The host reads the target, so the target is what the prop's type checks.

    Args:
        value: The candidate value.
        prop: Definition of the prop it would fill.

    Returns:
        Whether the binding may fill the prop, or None for any other value.
    """
    if not (isinstance(value, Mapping) and is_binding(value)):
        return None
    if binding_refusal(value, prop) is not None:
        return False
    target, _phase = check_binding(cast("Mapping[str, object]", value))
    return validate_prop(target, prop)


def _is_native_float(value: object) -> bool:
    try:
        validate_number(value, {"type": "float"})
    except IrValidationError:
        return False
    return True


def _valid_value(value: object, prop: PropDef) -> bool:
    try:
        validate_value(value, str(prop.value_type), REGISTRY.value_types)
        validate_bounds(value, prop.minimum, prop.maximum)
    except IrValidationError:
        return False
    return True


def validate_modifier(value: object, *, intents: Intents | None = None) -> None:
    """Validate ordered operations using generated modifier definitions.

    A modifier is an object holding its operations, the only shape Python
    writes; any other is refused. Invalid JSON propagates IrValidationError
    from the shared checker.

    Args:
        value: Ordinary or frozen modifier object.
        intents: The snapshot's intent contracts, for click actions.

    Raises:
        IrValidationError: If operations, props or action references are invalid.
    """
    check_json(value)
    if not isinstance(value, Mapping):
        raise IrValidationError("modifier must be an object")
    if set(value) != {"operations"}:
        raise IrValidationError("modifier must hold exactly its operations")
    operations = value["operations"]
    if not isinstance(operations, list | tuple):
        raise IrValidationError("modifier operations must be an array")
    for operation in operations:
        _validate_operation(operation, intents)


def _validate_operation(operation: object, intents: Intents | None) -> None:
    """Check one modifier operation against its catalog definition."""
    if not isinstance(operation, Mapping) or not isinstance(operation.get("type"), str):
        raise IrValidationError("invalid modifier operation")
    name = operation["type"]
    spec = REGISTRY.modifiers.get(name)
    if spec is None:
        raise IrValidationError("unknown modifier operation", modifier=name)
    for key, prop in spec.items():
        if prop.required and key not in operation:
            raise IrValidationError("missing modifier prop", modifier=name, prop=key)
    for key, item in operation.items():
        if key == "type":
            continue
        declared = spec.get(key)
        value = item
        if declared is not None and is_binding(item):
            refusal = binding_refusal(item, declared)
            if refusal is not None:
                raise IrValidationError(refusal, modifier=name, prop=key)
            value, _phase = check_binding(cast("Mapping[str, object]", item))
        if declared is None or not validate_prop(value, declared, intents=intents):
            raise IrValidationError("invalid modifier prop", modifier=name, prop=key)
