"""Codegen for a state family the pin implies (ADR-0058): validate, call, import.

A ``properties`` state names its holder's factory and settable properties; the
adapter remembers the holder through the factory and reconciles each property
with the renderer's generic ``reconcileProperty``. A property the factory seeds
is driven by re-creating the holder at the new value rather than by its setter,
since the factory sets what the setter does not (the TimePicker dial's angle).
"""

from __future__ import annotations

from typing import Any

from pycompose.codegen.adapter_helpers import _camel
from pycompose.codegen.literals import kotlin_string
from pycompose.codegen.rules import DOTTED_NAME, die
from pycompose.codegen.state_families import property_props, report_name

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
    for name, spec in state["properties"].items():
        prop = f"model.props.{_camel(name)}"
        narrow = NATIVE.get(spec["nativeType"], "")
        if spec.get("nullable"):
            desired = f"{prop}.wanted {{ it.{DECODE[spec['type']]}{narrow} }}"
        else:
            desired = f"{prop}?.let {{ Wanted(it{narrow}) }}"
        lines.append(f"val {native}{_title(name)} = {desired}")
        if "seed" in spec:
            # Absent from the app, a re-created holder keeps what the last had.
            seeded.append(
                f"{spec['seed']['parameter']} = {native}{_title(name)}?.value"
                f" ?: {seeds}.previous?.{name}"
                f" ?: {_literal(spec['seed']['default'], spec['nativeType'])}"
            )
    if seeded:
        lines += [
            f"val {seeds} = remember {{ Reseed<{state['holder']}>() }}",
            f"val {held} = key({seeds}.generation) "
            f"{{ {state['factory']}({', '.join(seeded)}) }}",
        ]
    else:
        lines.append(f"val {held} = {state['factory']}()")
    for name, spec in state["properties"].items():
        write = (
            f"{{ {seeds}.from({held}) }}, seeded = true"
            if "seed" in spec
            else f"{{ {held}.{name} = it }}"
        )
        lines.append(
            f'context.reconcileProperty({held}, "{name}", {native}{_title(name)}, '
            f"model.props.{report_name(name)}, {{ {held}.{name} }}, "
            f"{write}) {{ JsonPrimitive(it) }}"
        )
    return lines


def _title(name: str) -> str:
    return name[:1].upper() + name[1:]


def _literal(value: Any, native: str) -> str:
    """A literal default, spelled as the property's Kotlin type."""
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
    if set(state) != {"native", "kind", "holder", "factory", "properties"}:
        die(f"{where}: a derived family has native, kind, holder, factory, properties")
    for key in ("holder", "factory"):
        if not isinstance(state[key], str) or not DOTTED_NAME.fullmatch(state[key]):
            die(f"{where}: {key!r} must be a dotted name")
    properties = state["properties"]
    if not isinstance(properties, dict) or not properties:
        die(f"{where}: 'properties' must name the holder's properties")
    for prop, spec in property_props(state).items():
        if props.get(prop) != spec:
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
    for spec in state["properties"].values():
        if spec.get("nullable"):
            qualified.add("com.pycompose.renderer.wanted")
            if spec["type"] != "string":
                qualified.add(f"kotlinx.serialization.json.{DECODE[spec['type']]}")
    return qualified
