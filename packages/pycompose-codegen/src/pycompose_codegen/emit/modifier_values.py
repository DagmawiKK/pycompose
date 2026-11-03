"""How one wire value becomes the Kotlin value a modifier call passes.

A prop's wire type is not its Kotlin type: an ``integer`` may be an index or a
timestamp, and a dp rides the wire either as a bare number or as its family's
tagged object (ADR-0036). This module reads a prop's entry in the lock and says
what the generated call hands the parameter -- through the pin's resolver for a
value family, through the generated resolver for a family, and through the one
``bindingState`` for a prop the app bound.
"""

from __future__ import annotations

from typing import Any, cast

from pycompose.model.programs.bindings import animatable
from pycompose_codegen.emit.literals import kotlin_string
from pycompose_codegen.emit.modifier_bindings import animated
from pycompose_codegen.emit.rules import die
from pycompose_codegen.emit.values import resolver_call

READS = {
    "number": "double",
    "integer": "long",
    "boolean": "boolean",
    "string": "content",
}
"""How a scalar is read off its ``JsonPrimitive``."""

NARROW = {"Float": ".toFloat()", "Int": ".toInt()"}
"""From the wire's Kotlin type (Double, Long) to the parameter's own."""


def converter(spec: dict[str, Any], converters: dict[str, dict[str, Any]]) -> str:
    """The Kotlin expression naming a prop type's animation converter."""
    entry = converters.get(cast("str", spec.get("animation")))
    if entry is None:
        die(f"an animatable prop of type {spec.get('animation')!r} has no converter")
    return cast("str", entry["expression"])


def literal(spec: dict[str, Any]) -> str:
    """A scalar default, spelled as the parameter's Kotlin type."""
    value = spec["default"]
    if isinstance(value, bool):
        return "true" if value else "false"
    if spec.get("nativeType") == "Float":
        return f"{float(value)}f"
    if spec.get("nativeType") == "Int":
        return str(int(value))
    return repr(value)


def resolved(family: str, value: str) -> str:
    """A family's tagged object, through the generated resolver."""
    return resolver_call(family, value) + ".getOrThrow()"


def prop_value(spec: dict[str, Any], native: str) -> str:
    """The Kotlin value a prop of this spec passes, read from ``value``.

    A dp or number may stand as an expression over holder streams, which the
    host evaluates from the streams the snapshot publishes.

    Args:
        spec: The prop's lock entry.
        native: The Kotlin type of the parameter receiving it.

    Returns:
        Kotlin source over a plain wire value named ``value``.
    """
    if "valueType" in spec:
        return resolved(spec["valueType"], "value")
    if spec["type"] == "actionId":
        return "{ dispatch(value.jsonPrimitive.content) }"
    if spec["type"] == "dp":
        plain = (
            "com.pycompose.renderer.PropResolver"
            ".dp(value.jsonPrimitive.double).getOrThrow()"
        )
        return (
            "if (Expressions.isExpression(value)) "
            f"dpValue(value, streams) else {plain}"
        )
    if spec["type"] == "number":
        decoded = "numberValue(value, streams)"
    else:
        decoded = f"value.jsonPrimitive.{READS[spec['type']]}"
    return decoded + NARROW.get(native.rsplit(".", 1)[-1], "")


def decoded(spec: dict[str, Any], argument: dict[str, Any]) -> str:
    """The Kotlin value one prop of a direct call passes, read from ``value``.

    A family's tagged object goes through its resolver; a dp also rides the
    wire as a bare number (ADR-0036) or as an expression over holder streams.
    """
    if spec.get("valueType") == "Dp" and spec["type"] == "dp":
        riding = "com.pycompose.renderer.PropResolver.dp(value.jsonPrimitive.double)"
        return (
            "if (Expressions.isExpression(value)) "
            "dpValue(value, streams) "
            f"else if (value is JsonObject) {resolved('Dp', 'value')} "
            f"else {riding}.getOrThrow()"
        )
    return prop_value(spec, argument["type"])


def fallback(name: str, spec: dict[str, Any], native: str) -> str:
    """The Kotlin value a prop takes when the operation omits it.

    Args:
        name: The prop's wire name, for the report.
        spec: The prop's lock entry.
        native: The Kotlin type of the parameter receiving it.

    Returns:
        Kotlin source for the pin's default.
    """
    named = spec.get("nativeDefault") or spec.get("fallback")
    kind = native.rsplit(".", 1)[-1]
    if "default" not in spec or ("valueType" in spec and named):
        # A value, a colour or a named constant falls back on what the pin names.
        if named is None:
            die(f"modifier prop {name!r} has no default to fall back on")
        return cast("str", named)
    default = spec["default"]
    if isinstance(default, str):
        return kotlin_string(default)
    if isinstance(default, bool):
        return "true" if default else "false"
    if kind == "Dp":
        return f"androidx.compose.ui.unit.Dp({float(default)}f)"
    if kind == "Float":
        return f"{float(default)}f"
    return repr(default)


def passed(
    prop: str,
    spec: dict[str, Any],
    argument: dict[str, Any],
    converters: dict[str, dict[str, Any]],
) -> str:
    """One argument of a direct call: the prop's value, or its default when absent."""
    if animatable(spec):
        decode = animated(converter(spec, converters), "wire", decoded(spec, argument))
        present = f'op.getValue("{prop}").let {{ wire -> {decode} }}'
    else:
        present = f'op.getValue("{prop}").let {{ value -> {decoded(spec, argument)} }}'
    if spec.get("required"):
        return present
    default = fallback(prop, spec, argument["type"])
    return f'if ("{prop}" in op) {present} else {default}'


def argument(
    name: str,
    spec: dict[str, Any],
    parameter: str,
    converters: dict[str, dict[str, Any]],
) -> str:
    """One named argument of a scoped call, decoded from the operation's JSON."""
    present = f'op.getValue("{name}")'
    if "valueType" in spec:
        decode = resolved(spec["valueType"], "value")
    else:
        decode = f"value.jsonPrimitive.{READS[spec['type']]}"
        decode += NARROW.get(spec.get("nativeType", ""), "")
    read = (
        animated(converter(spec, converters), present, decode)
        if animatable(spec)
        else decode.replace("value", present, 1)
    )
    if spec.get("required"):
        return f"{parameter} = {read}"
    if "default" in spec:
        default = (
            kotlin_string(spec["default"])
            if isinstance(spec["default"], str)
            else literal(spec)
        )
    elif "nativeDefault" in spec:
        default = spec["nativeDefault"]
    else:
        die(f"scoped modifier prop {name!r} has no default to fall back on")
    return f'{parameter} = if ("{name}" in op) {read} else {default}'
