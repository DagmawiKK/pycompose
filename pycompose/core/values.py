"""Shared validation for approved, recursively described Compose values."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import cast

from pycompose.errors import IrValidationError
from pycompose.utils.json_canonical import JsonValue, check_json, freeze_json, thaw_json


class _Unset:
    """Constructor-only absence marker; never a wire value."""


UNSET = _Unset()
FLOAT_MAX = 3.4028234663852886e38
FLOAT_MIN = 1.401298464324817e-45


def construct(
    name: str,
    parameters: Mapping[str, object],
    definitions: Mapping[str, Mapping[str, object]],
) -> dict[str, JsonValue]:
    """Construct validated JSON data, preserving omitted versus null arguments.

    Invalid values propagate IrValidationError.

    Args:
        name: Approved constructor discriminator.
        parameters: Supplied constructor arguments, possibly including UNSET.
        definitions: Approved generated value descriptors.

    Returns:
        Detached, JSON-only value data.

    """
    data = {"type": name, **{k: v for k, v in parameters.items() if v is not UNSET}}
    family = definitions[name]["family"]
    validate_value(data, str(family), definitions)
    return cast("dict[str, JsonValue]", thaw_json(freeze_json(data)))


def validate_value(
    value: object,
    family: str,
    definitions: Mapping[str, Mapping[str, object]],
) -> None:
    """Validate a complete tagged value against its expected native family.

    Invalid JSON, fields, types or ranges propagate IrValidationError.

    Args:
        value: Ordinary or frozen JSON data.
        family: Expected Compose value family, never inferred from the contents.
        definitions: Approved generated value descriptors.

    """
    check_json(value)
    _value(value, family, definitions, 0)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise IrValidationError(message)


def _value(
    value: object,
    family: str,
    definitions: Mapping[str, Mapping[str, object]],
    depth: int,
) -> None:
    _require(depth < 64, "value nesting is too deep")
    _require(isinstance(value, Mapping), "Compose value must be a tagged object")
    data = cast("Mapping[str, object]", value)
    name = data.get("type")
    _require(isinstance(name, str), "value needs a constructor type")
    spec = definitions.get(cast("str", name))
    _require(spec is not None and spec.get("family") == family, "wrong value family")
    assert spec is not None
    parameters = cast("Mapping[str, Mapping[str, object]]", spec["parameters"])
    _require(set(data) <= {"type", *parameters}, "unknown value field")
    for key, rule in parameters.items():
        if key not in data:
            _require(not rule.get("required", False), f"missing value field: {key}")
        else:
            _parameter(data[key], rule, definitions, depth + 1)


def _parameter(
    value: object,
    rule: Mapping[str, object],
    definitions: Mapping[str, Mapping[str, object]],
    depth: int,
) -> None:
    if value is None:
        _require(rule.get("nullable") is True, "value field is not nullable")
        return
    kind = rule["type"]
    if kind == "value":
        _value(value, str(rule["valueType"]), definitions, depth)
        validate_bounds(value, rule.get("minimum"), rule.get("maximum"))
    elif kind == "list":
        _require(isinstance(value, list | tuple), "value field must be a list")
        items = cast("list[object] | tuple[object, ...]", value)
        _require(
            len(items) >= int(cast("int", rule.get("minItems", 0))),
            "too few value items",
        )
        for item in items:
            _parameter(
                item, cast("Mapping[str, object]", rule["items"]), definitions, depth
            )
    elif kind == "string":
        _require(isinstance(value, str), "value field must be a string")
        if "values" in rule:
            _require(
                value in cast("list[str]", rule["values"]), "unknown native constant"
            )
    elif kind == "boolean":
        _require(isinstance(value, bool), "value field must be a boolean")
    else:
        validate_number(value, rule)


def validate_number(value: object, rule: Mapping[str, object]) -> None:
    """Check scalar widths and bounds before native numeric rounding.

    Invalid values propagate IrValidationError.

    Args:
        value: Candidate JSON scalar.
        rule: Native numeric type and optional bounds.
    """
    kind = rule["type"]
    _require(kind in {"int", "long", "float", "double"}, "unknown value scalar type")
    _require(
        isinstance(value, int | float) and not isinstance(value, bool),
        "expected a number",
    )
    number = cast("int | float", value)
    if kind in {"int", "long"}:
        bits = 32 if kind == "int" else 64
        _require(isinstance(value, int), "native integer requires an integer")
        _require(
            -(2 ** (bits - 1)) <= number < 2 ** (bits - 1), "native integer overflow"
        )
    else:
        _require(abs(number) <= 1.7976931348623157e308, "native Double overflow")
        _require(math.isfinite(number), "native number must be finite")
        if kind == "float":
            _require(abs(number) <= FLOAT_MAX, "native Float overflow")
            _require(number == 0 or abs(number) >= FLOAT_MIN, "native Float underflow")
    if "minimum" in rule:
        _require(number >= cast("int | float", rule["minimum"]), "value below minimum")
    if "maximum" in rule:
        _require(number <= cast("int | float", rule["maximum"]), "value above maximum")


def validate_bounds(value: object, minimum: object, maximum: object) -> None:
    """Check contextual bounds on numeric scalar wrappers.

    Violated bounds propagate IrValidationError.

    Args:
        value: Already validated tagged value.
        minimum: Optional numeric lower bound.
        maximum: Optional numeric upper bound.

    """
    if isinstance(value, Mapping):
        number = value.get("value")
        if isinstance(number, int | float) and not isinstance(number, bool):
            if minimum is not None:
                _require(number >= cast("int | float", minimum), "value below minimum")
            if maximum is not None:
                _require(number <= cast("int | float", maximum), "value above maximum")
