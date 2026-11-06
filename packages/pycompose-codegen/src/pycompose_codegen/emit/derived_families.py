"""Codegen for a state family the pin implies (ADR-0058): validate, call, import.

A ``properties`` state names its holder's factory and settable properties; the
adapter remembers the holder through the factory and reconciles each property
with the renderer's generic ``reconcileProperty``. A property the factory seeds
is driven by re-creating the holder at the new value rather than by its setter,
since the factory sets what the setter does not (the TimePicker dial's angle).
A factory argument (a date picker's ``SelectableDates``) is read the same way:
the holder is re-created when the app gives a different one.
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.emit.adapters.policy import camel, pascal
from pycompose_codegen.emit.literals import kotlin_string
from pycompose_codegen.emit.rules import DOTTED_NAME, die
from pycompose_codegen.emit.state_families import property_props, report_name
from pycompose_codegen.emit.values import resolver_call

DECODE = {
    "integer": "long",
    "number": "double",
    "boolean": "boolean",
    "string": "content",
}
"""How a nullable property's present value is read off its ``JsonPrimitive``."""

NATIVE = {"Int": ".toInt()", "Float": ".toFloat()"}
"""Narrowing from the wire's Kotlin type (Long, Double) to a property's own."""

SUFFIX = {"Long": "L", "Float": "f"}
"""A numeric literal's suffix in the property's Kotlin type."""


def properties_locals(state: dict[str, Any]) -> list[str]:
    """A derived family: the holder from its factory, each property reconciled.

    Args:
        state: A ``state`` block of kind ``properties``.

    Returns:
        The Kotlin locals.
    """
    native = state["native"]
    held = f"{native}Value"
    seeds = f"{native}Seeds"
    lines: list[str] = []
    seeded: list[str] = []
    keys: list[str] = []
    for name, spec in state.get("arguments", {}).items():
        # The factory reads it once, so it is resolved only as the holder is
        # created; a different one re-creates the holder.
        wire = f"model.props.{camel(name)}"
        seeded.append(
            f"{name} = {wire}?.let "
            f"{{ {resolver_call(spec['valueType'], 'it')}.getOrThrow() }} "
            f"?: {spec['default']}"
        )
        keys.append(wire)
    for name, spec in state.get("construct", {}).items():
        # What fixes the holder as it is created; a different one re-creates it.
        wire = f"model.props.{camel(name)}"
        seeded.append(f"{name} = {_constructed(wire, spec)}")
        keys.append(wire)
    for name, spec in state["properties"].items():
        prop = f"model.props.{camel(name)}"
        narrow = NATIVE.get(spec["nativeType"], "")
        if spec.get("nullable"):
            desired = f"{prop}.wanted {{ it.{DECODE[spec['type']]}{narrow} }}"
        elif spec["type"] == "number":
            # A number may be an expression over holder streams.
            desired = f"{prop}?.let {{ Wanted(context.number(it){narrow}) }}"
        else:
            desired = f"{prop}?.let {{ Wanted(it{narrow}) }}"
        lines.append(f"val {native}{pascal(name)}Wanted = {desired}")
        if "seed" in spec:
            # Absent from the app, a re-created holder keeps what the last had;
            # a stated null clears.
            wanted = f"{native}{pascal(name)}Wanted"
            literal = _literal(spec["seed"]["default"], spec["nativeType"])
            kept = f"{seeds}.previous?.{name}" + (
                "" if literal == "null" else f" ?: {literal}"
            )
            stated = (
                f"if ({wanted} != null) {wanted}.value else {kept}"
                if spec.get("nullable")
                else f"{wanted}?.value ?: {kept}"
            )
            seeded.append(f"{spec['seed']['parameter']} = {stated}")
    if any("seed" in spec for spec in state["properties"].values()):
        lines.append(f"val {seeds} = remember {{ Reseed<{state['holder']}>() }}")
        keys.insert(0, f"{seeds}.generation")
    if seeded:
        lines += [
            f"val {held} = key({', '.join(keys)}) {{",
            f"    {state['factory']}(",
            *(f"        {argument}," for argument in seeded),
            "    )",
            "}",
        ]
    else:
        lines.append(f"val {held} = {state['factory']}()")
    settles = state.get("settles")
    if settles:
        # Values report where the holder says they settle, and where a drive
        # leaves them when the holder made something else of it (a tick).
        fields = ", ".join(
            f'"{name}" to JsonPrimitive({held}.{name})' for name in state["properties"]
        )
        lines.append(
            f"val {native}Settled = context.reportSettled({held}, "
            f"model.props.{camel(settles)}, {{ {held}.{settles} = it }}) "
            f"{{ JsonObject(mapOf({fields})) }}"
        )
    for name, spec in state["properties"].items():
        after = f"; {native}Settled()" if settles else ""
        write = (
            f"{{ {seeds}.from({held}) }}, seeded = true"
            if "seed" in spec
            else f"{{ {held}.{name} = it{after} }}"
        )
        # A holder that settles through a callback reports there, not per change.
        report = "null" if settles else f"model.props.{report_name(name)}"
        answering = f", answering = model.props.{camel(settles)}" if settles else ""
        wanted = f"{native}{pascal(name)}Wanted"
        lines.append(
            f'context.reconcileProperty({held}, "{name}", {wanted}, '
            f"{report}, {{ {held}.{name} }}, "
            f"{write}{answering}) {{ JsonPrimitive(it) }}"
        )
    return lines


def _constructed(wire: str, spec: dict[str, Any]) -> str:
    """A creation-time prop as the factory takes it."""
    if spec["type"] == "value":
        resolved = resolver_call(spec["valueType"], "it")
        if "nativeDefault" in spec:
            return (
                f"{wire}?.let {{ {resolved}.getOrThrow() }} ?: {spec['nativeDefault']}"
            )
        return f"{wire}.let {{ {resolved}.getOrThrow() }}"
    return f"{wire}{NATIVE.get(spec['nativeType'], '')}"


def _literal(value: Any, native: str) -> str:
    """A literal default, spelled as the property's Kotlin type."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if native == "String":
        return kotlin_string(value)
    return f"{value}{SUFFIX.get(native, '')}"


def validate_properties(
    where: str, props: dict[str, Any], state: dict[str, Any]
) -> None:
    """Check a derived family: its holder, its factory, and every projected prop.

    Args:
        where: Prefix for error messages.
        props: The component's props, which must carry the projection.
        state: The raw ``state`` object of kind ``properties``.
    """
    if (
        not {"native", "kind", "holder", "factory", "properties"}
        <= set(state)
        <= {
            "native",
            "kind",
            "holder",
            "factory",
            "properties",
            "arguments",
            "construct",
            "settles",
        }
    ):
        die(
            f"{where}: a derived family has native, kind, holder, factory, "
            "properties and optionally arguments, construct and settles"
        )
    for key in ("holder", "factory"):
        if not isinstance(state[key], str) or not DOTTED_NAME.fullmatch(state[key]):
            die(f"{where}: {key!r} must be a dotted name")
    properties = state["properties"]
    if not isinstance(properties, dict) or not properties:
        die(f"{where}: 'properties' must name the holder's properties")
    for prop, spec in property_props(state).items():
        # A prop newer than its component carries the version it entered at,
        # the wire may annotate the type it animates as, and policy may narrow
        # its range where the holder refuses what the pin does not say.
        stated = {
            k: v
            for k, v in (props.get(prop) or {}).items()
            if k
            not in {"since", "animation", "phase", "minimum", "maximum", "description"}
        }
        if stated != spec:
            die(f"{where}: prop {prop!r} must project the holder as {spec}")


def property_imports(state: dict[str, Any]) -> set[str]:
    """What a derived family's reconcile lines call, and how they decode nulls.

    Args:
        state: A ``state`` block of kind ``properties``.

    Returns:
        Fully qualified imports.
    """
    qualified = {
        "com.pycompose.renderer.Wanted",
        "com.pycompose.renderer.reconcileProperty",
    }
    if any("seed" in spec for spec in state["properties"].values()):
        qualified |= {
            "androidx.compose.runtime.key",
            "androidx.compose.runtime.remember",
            "com.pycompose.renderer.Reseed",
        }
    if state.get("arguments") or state.get("construct"):
        qualified.add("androidx.compose.runtime.key")
    if state.get("settles"):
        qualified |= {
            "com.pycompose.renderer.reportSettled",
            "kotlinx.serialization.json.JsonObject",
        }
    if any(spec["type"] == "number" for spec in state["properties"].values()):
        qualified.add("com.pycompose.renderer.number")
    for spec in state["properties"].values():
        if spec.get("nullable"):
            qualified.add("com.pycompose.renderer.wanted")
            if spec["type"] != "string":
                qualified.add(f"kotlinx.serialization.json.{DECODE[spec['type']]}")
    return qualified
