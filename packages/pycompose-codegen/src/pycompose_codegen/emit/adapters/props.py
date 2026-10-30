"""One prop into the call's fragments, by the shape its entry declares.

A scalar is passed as the model holds it, a value-typed prop through its
family's resolver, a callback as a dispatch, a dp through Kotlin's own
conversion and a provider as a lambda the host fills.
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.emit.adapters.fragments import Fragments
from pycompose_codegen.emit.adapters.policy import (
    NUMERIC_CONVERSIONS,
    NUMERIC_KOTLIN,
    SCALAR_KOTLIN,
    camel,
)
from pycompose_codegen.emit.values import resolver_call


def render_prop(prop: str, spec: dict[str, Any], out: Fragments) -> bool:
    """Render one prop into `out`, or report that the adapter cannot be built.

    Args:
        prop: The prop's schema name.
        spec: Its schema entry.
        out: Collects the rendered pieces.

    Returns:
        False when the prop carries a decision a generator cannot make.
    """
    prop_type = spec["type"]
    prop_name = camel(prop)
    if prop_type == "modifier":
        return True
    if "provider" in spec:
        emitted = _render_provider(prop_name, spec, spec["provider"], out)
    elif prop_type == "value":
        emitted = render_value(prop_name, spec, out)
    elif prop_type == "color" and "valueType" in spec:
        emitted = out.add(_color(prop_name, spec))
    elif prop_type == "enum" and "valueType" in spec:
        emitted = out.add(_named(prop_name, spec))
    elif spec.get("content") is not None:
        emitted = _render_slot(prop_name, spec, out)
    elif prop_type == "actionId":
        callback = _callback(prop_name, spec)
        emitted = callback is not None and out.add(("", callback))
    elif prop_type == "dp":
        emitted = _render_dp(prop_name, spec, out)
    else:
        emitted = _render_scalar(prop_name, spec, out)
    return emitted


def _render_scalar(prop_name: str, spec: dict[str, Any], out: Fragments) -> bool:
    """Render a plain scalar prop, or refuse an undecodable one.

    Args:
        prop_name: The camelCase Kotlin property name.
        spec: The prop's schema entry.
        out: Collects the rendered pieces.

    Returns:
        False when the prop's type has no Kotlin mapping this generator knows.
    """
    if spec["type"] not in SCALAR_KOTLIN:
        # An enum or colour with no value family, or a resource: refused, as
        # no resolver says what its values are natively.
        return False
    if "indexOf" in spec:
        # Compose reads its items at this index while measuring and throws
        # outside them; the host clamps and reports, and with no items composes
        # nothing (ADR-0005).
        slot = spec["indexOf"]
        out.locals.append(
            f"val {prop_name}Value = context.index(model.props.{prop_name}, "
            f'model.children.inSlot("{slot}"), node.id)'
        )
        out.arguments.append(f"{prop_name} = {prop_name}Value")
        out.gates.append(f"{prop_name}Value != null")
    elif spec.get("required") or "default" in spec:
        # A nullable property would not compile where Compose wants a value.
        out.arguments.append(f"{prop_name} = {scalar_wire(prop_name, spec)}")
    return True


def scalar_wire(prop_name: str, spec: dict[str, Any]) -> str:
    """Read one scalar from the model, narrowing an Int- or Float-native value.

    Args:
        prop_name: The camelCase Kotlin property name.
        spec: The prop's schema entry.

    Returns:
        Kotlin source for the value Compose receives.
    """
    wire = f"model.props.{prop_name}"
    narrow = {"Int": "toInt()", "Float": "toFloat()"}.get(spec.get("nativeType", ""))
    if narrow:
        wire += f"?.{narrow}" if spec.get("nullable") else f".{narrow}"
    return wire


def _render_dp(prop_name: str, spec: dict[str, Any], out: Fragments) -> bool:
    """Render a dp prop through Kotlin's own ``Double.dp`` conversion.

    A dp prop rides the wire as a plain finite number; the number already means
    the density-independent unit, so no decoder sits between them. Absence is
    the interesting half: the model cannot hold a ``Dp``, so an optional prop
    names its pinned default in ``nativeDefault`` and the adapter chooses, with
    the native side owning the value it declared.

    Args:
        prop_name: The camelCase Kotlin property name.
        spec: The prop's schema entry.
        out: Collects the rendered pieces.

    Returns:
        True when the prop rendered; False leaves the adapter to the hands.
    """
    wire = f"model.props.{prop_name}"
    if spec.get("required") or "default" in spec:
        out.arguments.append(f"{prop_name} = {wire}.dp")
        return True
    if "nativeDefault" in spec:
        # Through a local: the model lives in another module, so its nullable
        # property does not smart-cast.
        out.locals.append(f"val {prop_name}Wire = {wire}")
        out.locals.append(
            f"val {prop_name}Value = if ({prop_name}Wire != null) "
            f"{prop_name}Wire.dp else {spec['nativeDefault']}"
        )
        out.arguments.append(f"{prop_name} = {prop_name}Value")
        return True
    return False


def _render_slot(prop_name: str, spec: dict[str, Any], out: Fragments) -> bool:
    """Render a flattened content slot.

    Args:
        prop_name: The camelCase Kotlin property name.
        spec: The prop's schema entry.
        out: Collects the rendered pieces.

    Returns:
        False when the slot is optional and would need a null check.
    """
    slot = _slot(prop_name, spec)
    if slot is None:
        return False
    argument, body = slot
    if argument:
        out.arguments.append(argument)
    out.trailing_lambda(body)
    return True


def _slot(prop_name: str, spec: dict[str, Any]) -> tuple[str, str] | None:
    """Render a prop flattened out of a Compose content slot.

    Args:
        prop_name: The camelCase Kotlin property name.
        spec: The prop's schema entry.

    Returns:
        ``(argument, trailing)`` where either may be empty, or None when the
        slot is optional and would need a null check -- a decision, not a
        derivation.
    """
    slot = spec.get("content")
    if slot is None:
        return None
    if not spec.get("required"):
        return None
    wrapped = f"{slot['composable']}(model.props.{prop_name})"
    parameter = slot.get("parameter")
    if parameter is not None:
        return f"{parameter} = {{ {wrapped} }}", ""
    return "", wrapped


def render_value(prop_name: str, spec: dict[str, Any], out: Fragments) -> bool:
    """Render a prop carrying a native value-family tag.

    Args:
        prop_name: The camelCase Kotlin property name.
        spec: The prop's schema entry.
        out: Collects the rendered pieces.

    Returns:
        True when the value could be resolved into a local.
    """
    family = spec["valueType"]
    wire = f"model.props.{prop_name}"
    declaration = ""
    if not spec.get("required"):
        declaration = f"val {prop_name}Wire = {wire}\n                "
        wire = f"{prop_name}Wire"
    call = resolver_call(family, wire) + ".getOrThrow()"
    if spec.get("nullable"):
        call = (
            f"when ({wire}) {{\n"
            "                    com.pycompose.ir.OptionalValue.Absent -> "
            f"{spec['nativeDefault']}\n"
            "                    com.pycompose.ir.OptionalValue.Null -> null\n"
            f"                    is com.pycompose.ir.OptionalValue.Present -> "
            f"{resolver_call(family, f'{wire}.value')}.getOrThrow()\n"
            "                }"
        )
    elif not spec.get("required"):
        call = f"if ({wire} != null) {call} else {spec['nativeDefault']}"
    return out.add(
        (
            f"{declaration}val {prop_name}Value = {call}",
            f"{prop_name} = {prop_name}Value",
        )
    )


def _named(prop_name: str, spec: dict[str, Any]) -> tuple[str, str]:
    """Render a named-constant prop: its tagged constant, or its native default.

    Args:
        prop_name: The camelCase Kotlin property name.
        spec: The prop's schema entry.

    Returns:
        The local declaration and the argument naming it.
    """
    wire = f"model.props.{prop_name}"
    if spec.get("required"):
        resolved = resolver_call(spec["valueType"], wire) + ".getOrThrow()"
    else:
        tagged = resolver_call(spec["valueType"], "it") + ".getOrThrow()"
        resolved = f"{wire}?.let {{ {tagged} }} ?: {spec['nativeDefault']}"
    return f"val {prop_name}Value = {resolved}", f"{prop_name} = {prop_name}Value"


def _color(prop_name: str, spec: dict[str, Any]) -> tuple[str, str]:
    """Render a colour prop: its tagged value, or an expression over streams.

    A colour crosses the wire only as its family's tagged object; an
    expression over holder streams is an object too, evaluated here each frame
    its streams move. Absent, the parameter takes the colour the hand-written
    adapter chose for it.

    Args:
        prop_name: The camelCase Kotlin property name.
        spec: The prop's schema entry.

    Returns:
        The local declaration and the argument naming it.
    """
    fallback = spec.get("fallback", "androidx.compose.ui.graphics.Color.Unspecified")
    tagged = resolver_call(spec["valueType"], "wire")
    value = f"{prop_name}Value"
    return (
        f"val {value}: androidx.compose.ui.graphics.Color = "
        f"when (val wire = model.props.{prop_name}) {{\n"
        "                    is JsonObject -> context.expressionColor(wire) "
        f"?: {tagged}.getOrDefault({fallback})\n"
        f"                    else -> {fallback}\n"
        "                }",
        f"{prop_name} = {value}",
    )


def _callback(prop_name: str, spec: dict[str, Any]) -> str | None:
    """Render one actionId prop as a Kotlin callback argument.

    Compose's ``onClick`` takes nothing and dispatches the bare actionId, while
    ``onCheckedChange`` hands back the new value and reports it alongside. Which
    of the two a callback is used to be invisible from the component entry; the
    schema's ``payload`` says so since 1.9.0, and guessing produces a callback
    with the wrong arity.

    Args:
        prop_name: The camelCase Kotlin property name.
        spec: The prop's schema entry.

    Returns:
        The argument, or None when the callback shape is one this cannot render.
    """
    payload = spec.get("payload")
    # An optional callback's action id is nullable: a call the app did not bind
    # reaches nobody, and the native default behaviour stays in charge.
    action = f"model.props.{prop_name}" if spec.get("required") else "it"
    bound = "" if spec.get("required") else f"model.props.{prop_name}?.let {{ "
    close = "" if spec.get("required") else " }"
    if not payload:
        return f"{prop_name} = {{ {bound}context.actions.dispatch({action}){close} }}"
    if len(payload) != 1:
        return None
    field_name, kind = payload[0]["name"], payload[0]["type"]
    if kind not in SCALAR_KOTLIN:
        return None
    return (
        f"{prop_name} = {{ {field_name} -> "
        f"{bound}context.event({action}, JsonPrimitive({field_name})){close} }}"
    )


def _render_provider(
    prop_name: str, spec: dict[str, Any], provider: dict[str, Any], out: Fragments
) -> bool:
    """Render a prop the native call receives as a zero-arg lambda.

    The app states a value in the snapshot, and the host reads it during
    composition to supply the lambda the native parameter declares. Python is
    never called from composition, and the parameter stays a value the app
    cannot name: the schema requires the prop, so the adapter has exactly one
    call shape.

    Args:
        prop_name: The camelCase Kotlin property name.
        spec: The prop's schema entry.
        provider: Its validated ``provider`` object.
        out: Collects the rendered pieces.

    Returns:
        False when the prop's type cannot be resolved, or the resolved type has
        no stated conversion to the pinned return type.
    """
    local: str
    wire: str | None
    if spec["type"] == "value":
        wire = None
        local = (
            f"val {prop_name}Value = "
            f"{resolver_call(spec['valueType'], f'model.props.{prop_name}')}"
            ".getOrThrow()"
        )
    elif spec["type"] in SCALAR_KOTLIN:
        wire = SCALAR_KOTLIN[spec["type"]]
        local = f"val {prop_name}Value = model.props.{prop_name}"
    else:
        return False
    argument = _provided(f"{prop_name}Value", wire, provider["returns"])
    if argument is None:
        return False
    return out.add((local, f"{provider['native']} = {{ {argument} }}"))


def _provided(expression: str, wire: str | None, target: str) -> str | None:
    """Coerce a resolved value to a provider's pinned return type.

    ``wire`` is the Kotlin type the generator resolved the prop into, or None
    when that type is a family resolver's contract: the compiler checks the
    lambda against the pinned parameter and composegen's check verifies ``target``
    against the pin, so no coercion is invented there.

    Args:
        expression: The Kotlin expression holding the resolved value.
        wire: The Kotlin type of that expression, when the generator knows it.
        target: The provider's ``returns`` type.

    Returns:
        The coerced expression, or None when the pair has no stated conversion.
    """
    if wire is None or wire == target:
        return expression
    if wire in NUMERIC_KOTLIN and target in NUMERIC_KOTLIN:
        conversion = NUMERIC_CONVERSIONS.get((wire, target))
        return None if conversion is None else f"{expression}.{conversion}()"
    return None
