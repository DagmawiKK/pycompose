"""A prop the app may bind: its value, read where the call reads it.

A component reads its props while composing, so a bound one recomposes the
component's own subtree per frame. Wrapping the component in a graphics layer
to move the read off composition would animate the wrong property and change
clipping and z-order, so it is never done.

The pin still says what to animate with: the lock records, per prop, the Kotlin
type whose ``TwoWayConverter`` Compose declares. A prop without one is not
offered a binding at all, and is passed as a plain value.

Every bound prop declares the same state first -- the value, kept at its target
-- and then reads it: straight into the call, into a provider lambda Compose
invokes later, or through the items-count clamp a tab index needs.
"""

from __future__ import annotations

from typing import Any, cast

from pycompose_codegen.emit.adapters.fragments import Fragments
from pycompose_codegen.emit.values import resolver_call

UNSPECIFIED = "androidx.compose.ui.graphics.Color.Unspecified"
"""What a colour prop with no stated fallback resolves to: the colour in scope."""

PHASE = "com.pycompose.program.Phase"
"""The phases a binding names, as the host's enum spells them."""

READS = {
    "number": "double",
    "dp": "double",
    "integer": "long",
    "boolean": "boolean",
    "string": "content",
}
"""How a scalar is read off its ``JsonPrimitive``."""


def converter(
    spec: dict[str, Any], converters: dict[str, dict[str, Any]]
) -> str | None:
    """The Kotlin expression naming the converter the pin declares for a prop.

    Args:
        spec: The prop's lock entry.
        converters: The lock's converter table, by animated Kotlin type.

    Returns:
        The expression, or None when the pin declares no converter for it.
    """
    entry = converters.get(cast("str", spec.get("animation")))
    return None if entry is None else cast("str", entry["expression"])


def plain(spec: dict[str, Any]) -> list[str]:
    """Read a plain wire value as the type the converter animates.

    A dp or number may stand as an expression over holder streams, which the
    host evaluates; ``context.number`` reads either form.

    Args:
        spec: The prop's lock entry.

    Returns:
        Kotlin source over a plain wire value named ``plain``, as lines indented
        relative to the first.
    """
    if spec["type"] == "color":
        # A nullable producer's absence is handled before any value is read.
        fallback = spec.get("fallback", UNSPECIFIED).replace("null", UNSPECIFIED)
        tagged = resolver_call(spec["valueType"], "plain")
        return [
            "when (plain) {",
            "    is JsonObject -> context.expressionColor(plain)",
            f"        ?: {tagged}.getOrDefault({fallback})",
            f"    else -> {fallback}",
            "}",
        ]
    if spec["type"] == "dp":
        return ["context.number(plain).dp"]
    native = cast("str", spec["animation"]).rsplit(".", 1)[-1]
    narrow = {"Float": ".toFloat()", "Int": ".toInt()"}.get(native, "")
    if spec["type"] == "number":
        return [f"context.number(plain){narrow}"]
    return [f"plain.jsonPrimitive.{READS[spec['type']]}{narrow}"]


def plain_imports(spec: dict[str, Any]) -> set[str]:
    """What reading this prop, plain or bound, needs imported.

    Args:
        spec: The prop's lock entry.

    Returns:
        Fully qualified names, for the adapter's import list.
    """
    if not deferred(spec):
        helper = {"color": "boundColor", "dp": "boundDp"}.get(spec["type"], "bound")
        reads = set() if helper != "bound" else _read_imports(spec)
        # A dp fallback is spelled with Kotlin's extension property.
        units = {"androidx.compose.ui.unit.dp"} if spec["type"] == "dp" else set()
        return {f"com.pycompose.renderer.{helper}", *reads, *units}
    return _read_imports(spec)


def _read_imports(spec: dict[str, Any]) -> set[str]:
    """What decoding one plain wire value of this prop's type needs imported."""
    if spec["type"] == "color":
        return {
            "kotlinx.serialization.json.JsonObject",
            "com.pycompose.renderer.expressionColor",
        }
    if spec["type"] == "dp":
        # Kotlin's own conversion is an extension property, and the number is
        # read through the renderer's one decode.
        return {"androidx.compose.ui.unit.dp", "com.pycompose.renderer.number"}
    if spec["type"] == "number":
        return {"com.pycompose.renderer.number"}
    reads = {f"kotlinx.serialization.json.{READS[spec['type']]}"}
    reads.add("kotlinx.serialization.json.jsonPrimitive")
    return reads


def model_nullable(spec: dict[str, Any]) -> bool:
    """Whether the generated model can hold no value when the app states none.

    A required prop is always there, and a prop with a model default is filled
    by that default; only the rest is null in the model.

    Args:
        spec: The prop's lock entry.

    Returns:
        True when the model's field is nullable.
    """
    return "default" not in spec and not spec.get("required")


def fallback(spec: dict[str, Any]) -> str | None:
    """What the component uses when the prop is omitted.

    Args:
        spec: The prop's lock entry.

    Returns:
        Kotlin source for the value, or None when the lock names none.
    """
    if spec["type"] == "color":
        return cast("str", spec.get("fallback", UNSPECIFIED))
    if "nativeDefault" in spec:
        return cast("str", spec["nativeDefault"])
    if "default" not in spec:
        return None
    value = spec["default"]
    native = cast("str", spec["animation"]).rsplit(".", 1)[-1]
    literal = {
        "Float": f"{float(value)}f",
        "Int": str(int(value)),
        "Dp": f"androidx.compose.ui.unit.Dp({float(value)}f)",
    }
    return literal.get(native, repr(value))


def deferred(spec: dict[str, Any]) -> bool:
    """Whether the value is read after the call: by a provider, or an index clamp.

    Args:
        spec: The prop's lock entry.

    Returns:
        True when the adapter keeps the value's state rather than reading it.
    """
    return "provider" in spec or "indexOf" in spec


def state_lines(
    prop_name: str,
    spec: dict[str, Any],
    expression: str,
    read: list[str],
) -> list[str]:
    """Declare one prop's state: its value, kept at the target the app stated.

    The lines are indented relative to the adapter body, so a caller adds its
    own margin and a long decode stays inside the generated width budget.

    Args:
        prop_name: The camelCase Kotlin property name.
        spec: The prop's lock entry.
        expression: The converter the pin declares for the prop's type.
        read: Kotlin source decoding one plain wire value, as lines.

    Returns:
        The declaration's lines.
    """
    absent = "?" if model_nullable(spec) else ""
    phase = f"{PHASE}.{spec.get('phase', 'composition').capitalize()}"
    return [
        f"val {prop_name}State =",
        f"    model.props.{prop_name}{absent}.let {{ wire ->",
        f"        com.pycompose.renderer.bindingState(wire, {expression}, {phase}) {{",
        "            plain ->",
        *(f"            {line}" for line in read),
        "        }",
        "    }",
    ]


def render_bound(
    prop_name: str,
    spec: dict[str, Any],
    out: Fragments,
    converters: dict[str, dict[str, Any]],
) -> bool:
    """Render a prop the app may bind, read in the phase the pin gives it.

    Args:
        prop_name: The camelCase Kotlin property name.
        spec: The prop's lock entry.
        out: Collects the rendered pieces.
        converters: The lock's converter table, by animated Kotlin type.

    Returns:
        False when the pin declares no converter, or no value for absence.
    """
    expression = converter(spec, converters)
    if expression is None:
        return False
    if not deferred(spec):
        value = _composed(prop_name, spec, expression)
        if value is None:
            return False
        out.locals.append(f"val {prop_name}Value = {value}")
        out.arguments.append(f"{prop_name} = {prop_name}Value")
        return True
    out.locals.extend(state_lines(prop_name, spec, expression, plain(spec)))
    if "indexOf" in spec:
        # Compose reads its items at this index while measuring and throws
        # outside them; the host clamps and reports, and with no items composes
        # nothing (ADR-0005).
        out.locals.append(
            f"val {prop_name}Value = context.index({prop_name}State.value.toLong(), "
            f'model.children.inSlot("{spec["indexOf"]}"), node.id)'
        )
        out.gates.append(f"{prop_name}Value != null")
        out.arguments.append(f"{prop_name} = {prop_name}Value")
        return True
    # The native parameter is a lambda or a producer; Compose invokes it for the
    # value while it draws, so the state is declared here and read there. An
    # absent nullable producer is the component's own null.
    provider = spec["provider"]
    if model_nullable(spec):
        produced = provided(provider, "state.value")
        value = f"{prop_name}State?.let {{ state -> {produced} }}"
    else:
        value = provided(provider, f"{prop_name}State.value")
    out.arguments.append(f"{provider['native']} = {value}")
    return True


def _composed(prop_name: str, spec: dict[str, Any], expression: str) -> str | None:
    """A prop read in the call: one helper, the fallback stated once.

    A plain value is read as it stands and keeps no state; a binding travels
    through the converter.
    """
    wire = f"model.props.{prop_name}"
    absent = fallback(spec) if model_nullable(spec) else None
    if model_nullable(spec) and absent is None:
        return None
    if spec["type"] in {"color", "dp"} and absent is not None:
        helper = "boundColor" if spec["type"] == "color" else "boundDp"
        return f"context.{helper}({wire}, {expression}, {absent})"
    read = " ".join(line.strip() for line in plain(spec))
    call = f"bound({{wire}}, {expression}) {{ plain -> {read} }}"
    if absent is None:
        return call.replace("{wire}", wire)
    return f"{wire}?.let {{ wire -> {call.replace('{wire}', 'wire')} }} ?: {absent}"


def provided(provider: dict[str, Any], expression: str) -> str:
    """What the component asks for the value through: a lambda or a producer.

    Args:
        provider: The prop's ``provider`` record.
        expression: Kotlin source for the value, read each time it is asked.

    Returns:
        Kotlin source for the argument.
    """
    if "interface" not in provider:
        return f"{{ {expression} }}"
    return (
        f"object : {provider['interface']} {{ "
        f"override fun {provider['member']}() = {expression} }}"
    )
