"""Generate the Kotlin adapters that are mechanically derivable.

    python tools/schema/gen.py          # writes GeneratedAdapters.kt too

ADR-0011's addendum ended with "you would only need manual adapters for
non-standard components", and that was optimistic. Roughly half the current
catalog is mechanical; the rest is not, and pretending otherwise would generate
code that does not compile.

An adapter is generated when **every** one of these holds:

* no children -- a component that composes content needs its lambda written by
  hand, because where the children go is the decision
* every prop is a scalar, a modifier, or an actionId
* no prop the host resolves by name, such as a resource

Everything else stays in ``BuiltinComponents.kt``. A test asserts that every
registered component has an adapter in exactly one of the two, so neither file
can quietly fall behind the schema -- which is the failure that produced a blank
screen once already.
"""

from __future__ import annotations

from typing import Any

COMPOSE_PACKAGE = {
    "Box": "androidx.compose.foundation.layout",
    "Button": "androidx.compose.material3",
    "Checkbox": "androidx.compose.material3",
    "Column": "androidx.compose.foundation.layout",
    "FilterChip": "androidx.compose.material3",
    "Image": "androidx.compose.foundation",
    "Row": "androidx.compose.foundation.layout",
    "Spacer": "androidx.compose.foundation.layout",
    "Text": "androidx.compose.material3",
    "TextButton": "androidx.compose.material3",
    "TextField": "androidx.compose.material3",
}
"""Where each component's Compose class lives.

Placeholder knowledge, and the only part of this file that is not derived from the
schema. Phase C removes it: the API dump already says which ``*Kt`` class each
composable hangs off, so the package is derivable rather than listed.
"""

SCALAR_KOTLIN = {
    "string": "String",
    "boolean": "Boolean",
    "integer": "Long",
    "number": "Double",
}

MECHANICAL = {"string", "boolean", "integer", "number", "actionId", "modifier"}
"""Schema prop types an adapter can render with no decision and no decoder.

``color``, ``enum`` and ``resource`` are deliberately absent. Their encodings are
declared in the schema (1.8.0) but the host has no PropResolver to decode them
yet, and generating an adapter that passes a ``String`` where Compose wants a
``Color`` would not compile.
"""


def _camel(name: str) -> str:
    """Return a snake_case wire name as camelCase.

    Args:
        name: The schema's prop name.

    Returns:
        The Kotlin property name.
    """
    head, *rest = name.split("_")
    return head + "".join(word[:1].upper() + word[1:] for word in rest)


def is_mechanical(entry: dict[str, Any]) -> bool:
    """Report whether a component's adapter can be derived from its schema.

    Args:
        entry: The component's schema entry.

    Returns:
        True when every prop renders without a human decision.
    """
    if entry.get("adapter") == "manual":
        return False
    if entry.get("children", {}).get("allowed"):
        return False
    return all(
        spec.get("type") in MECHANICAL for spec in entry.get("props", {}).values()
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
    if not payload:
        return f"{prop_name} = {{ context.actions.dispatch(model.props.{prop_name}) }}"
    if len(payload) != 1:
        return None
    field_name, kind = payload[0]["name"], payload[0]["type"]
    if kind not in SCALAR_KOTLIN:
        return None
    return (
        f"{prop_name} = {{ {field_name} -> "
        f"context.event(model.props.{prop_name}, JsonPrimitive({field_name})) }}"
    )


def composables(name: str, entry: dict[str, Any]) -> set[str]:
    """List the Compose imports one adapter needs beyond the component itself.

    A flattened content slot is its own dependency: ``Button`` compiles without
    ``Text`` in scope until the slot becomes a real ``Text`` call.

    Args:
        name: The component's schema name.
        entry: Its schema entry.

    Returns:
        Simple class names the generated code references, excluding ``name``.
    """
    used = {
        slot["composable"]
        for spec in entry.get("props", {}).values()
        if (slot := spec.get("content")) is not None
    }
    used.discard(name)
    return used


def render(name: str, entry: dict[str, Any]) -> str:
    """Render one adapter.

    A prop is passed only when its generated Kotlin property is non-null, which
    is exactly when the schema marks it required or gives it a default.
    ``Button.enabled`` has a default and passes; an optional prop with no declared
    default is a ``Boolean?`` in the model and is omitted, leaving Compose's own
    default in charge. Passing a nullable through is the mistake that turns a
    generator into something that does not compile.

    A prop flattened out of a content slot becomes a lambda wrapping the slot's
    declared composable -- ``Text(model.props.text)`` inside ``Button``, or
    ``label = { Text(model.props.label) }`` for ``FilterChip``, which names its
    slot. Only a required slot renders: an optional one needs a null check, and
    that is a decision.

    Args:
        name: The component's schema name.
        entry: Its schema entry.

    Returns:
        The adapter as Kotlin, or an empty string when it cannot be derived.
    """
    if not is_mechanical(entry):
        return ""

    arguments = ["modifier = modifier"]
    trailing: list[str] = []
    for prop, spec in entry.get("props", {}).items():
        prop_type = spec["type"]
        prop_name = _camel(prop)
        if prop_type == "modifier":
            continue

        slot = spec.get("content")
        if slot is not None:
            if not spec.get("required"):
                return ""
            wrapped = f"{slot['composable']}(model.props.{prop_name})"
            parameter = slot.get("parameter")
            if parameter is not None:
                arguments.append(f"{parameter} = {{ {wrapped} }}")
            else:
                trailing.append(f"                    {wrapped}")
            continue

        if prop_type == "actionId":
            callback = _callback(prop_name, spec)
            if callback is None:
                return ""
            arguments.append(callback)
            continue

        if prop_type not in SCALAR_KOTLIN:
            # color, enum, resource: the encodings are declared but the host has
            # no PropResolver to decode them, so no honest mapping exists yet.
            return ""
        if not (spec.get("required") or "default" in spec):
            continue
        arguments.append(f"{prop_name} = model.props.{prop_name}")

    body = "\n".join(f"                    {argument}," for argument in arguments)
    tail = ""
    if trailing:
        tail = " {\n" + "\n".join(trailing) + "\n            }"
    node = f"{name}Node"
    return (
        f'            .register("{name}") {{ node, modifier, context ->\n'
        f"                val model = node as {node}\n"
        f"                {name}(\n"
        f"{body}\n"
        f"                ){tail}\n"
        f"            }}"
    )


def render_file(registry: dict[str, Any]) -> str:
    """Render every mechanically-derivable adapter as one Kotlin object.

    Args:
        registry: The parsed schema.

    Returns:
        The generated source, or an empty string when nothing qualifies.
    """
    blocks: list[str] = []
    imports: set[str] = set()
    for name in sorted(registry["components"]):
        entry = registry["components"][name]
        block = render(name, entry)
        if block:
            blocks.append(block)
            package = COMPOSE_PACKAGE.get(name)
            if package is None:
                continue
            imports.add(f"import {package}.{name}")
            for extra in composables(name, entry):
                imports.add(f"import {package}.{extra}")
            imports.add(f"import com.pycompose.ir.generated.{name} as {name}Node")
    if not blocks:
        return ""

    header = [
        "// Generated by tools/schema/gen.py from schema/components.json.",
        "// Do not edit: change the schema and regenerate.",
        "package com.pycompose.host.ui",
        "",
        "import com.pycompose.renderer.ComponentRegistry",
        "import kotlinx.serialization.json.JsonPrimitive",
    ]
    body = [
        "",
        "/** Adapters derived mechanically from the schema, for every component whose",
        " * props carry no decision a generator cannot make. */",
        "object GeneratedAdapters {",
        "    private fun ComponentRegistry.Builder.generated():",
        "        ComponentRegistry.Builder =",
        "        this",
        *blocks,
        "    fun register(into: ComponentRegistry.Builder):",
        "        ComponentRegistry.Builder =",
        "        into.generated()",
        "}",
    ]
    return "\n".join([*header, *sorted(imports), *body]) + "\n"
