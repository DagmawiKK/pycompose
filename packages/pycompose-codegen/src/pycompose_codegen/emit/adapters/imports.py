"""The imports a generated adapter needs beyond its component.

Kotlin resolves an extension -- ``.dp``, a renderer helper -- only where it is
imported, so each fact in an entry that makes the adapter call one names the
import with it.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pycompose.model.catalog.vocabulary import STATE_STREAMS
from pycompose.model.programs.bindings import animatable
from pycompose_codegen.emit.adapters.bound import plain_imports
from pycompose_codegen.emit.adapters.state import state_call
from pycompose_codegen.emit.adapters.text_echo import (
    CARET_IMPORTS,
    EDIT_IMPORTS,
    echoes,
    follows_caret,
)
from pycompose_codegen.emit.derived_families import property_imports
from pycompose_codegen.emit.state_families import attach_gate


def _state_imports(entry: dict[str, Any]) -> set[str]:
    """What the component's state holder needs imported, if it has one."""
    state = entry.get("state")
    if state is None:
        return set()
    if state["kind"] == "properties":
        return set(property_imports(state))
    if state["kind"] == "positional":
        # One runtime for every positional holder; its count is the children.
        return {"com.pycompose.renderer.positional", "com.pycompose.renderer.unslotted"}
    qualified = {f"com.pycompose.renderer.{state_call(state['kind'])}"}
    if state["kind"] in STATE_STREAMS:
        qualified.add("com.pycompose.renderer.publish")
    if attach_gate(state, entry.get("props", {})) is not None:
        # The holder rides the component's modifier, so the extension making
        # that ride callable must be imported where the call is written.
        qualified.add("com.pycompose.renderer.attachTo")
    return qualified


def extra_imports(
    entry: dict[str, Any], converters: dict[str, dict[str, Any]] | None = None
) -> set[str]:
    """List the fully qualified imports an adapter needs beyond its component.

    Args:
        entry: The component's schema entry.
        converters: The lock's animation converters, by Kotlin type.

    Returns:
        Import statements' targets, sorted by the caller.
    """
    qualified = _prop_imports(
        entry.get("props", {}).values(), converters or {}
    ) | _state_imports(entry)
    if follows_caret(entry.get("props", {})):
        qualified |= CARET_IMPORTS
    elif echoes(entry.get("props", {})):
        qualified |= EDIT_IMPORTS
    if entry.get("boxed"):
        qualified.add("androidx.compose.foundation.layout.Box")
    if (transient := entry.get("transient")) is not None:
        qualified.add(f"com.pycompose.renderer.{transient['kind']}")
    slots = [entry.get("children", {}), *entry.get("slots", {}).values()]
    for slot in slots:
        if slot.get("consume") == "paddingValues":
            qualified.update(
                {
                    "androidx.compose.foundation.layout.Column",
                    "androidx.compose.foundation.layout.padding",
                    "androidx.compose.ui.Modifier",
                }
            )
    if entry.get("children", {}).get("kind") == "items":
        # The primary children are the unslotted ones, and an extension becomes
        # callable only where it is imported.
        qualified.update(
            {
                "com.pycompose.renderer.windowedItems",
                "com.pycompose.renderer.unslotted",
            }
        )
    if entry.get("children", {}).get("kind") == "indexed":
        # One page per child: the unslotted ones, in order.
        qualified.add("com.pycompose.renderer.unslotted")
    if any("indexOf" in spec for spec in entry.get("props", {}).values()):
        qualified.update(
            {"com.pycompose.renderer.index", "com.pycompose.renderer.inSlot"}
        )
    if any(slot.get("kind") == "items" for slot in entry.get("slots", {}).values()):
        qualified.update(
            {
                "androidx.compose.foundation.lazy.items",
                "com.pycompose.renderer.inSlot",
            }
        )
    return qualified


def _prop_imports(
    specs: Iterable[dict[str, Any]], converters: dict[str, dict[str, Any]]
) -> set[str]:
    """The imports a component's props need, beyond the resolvers they name."""
    qualified: set[str] = set()
    for spec in specs:
        if animatable(spec):
            # A bound prop reads its value through the pin's converter.
            entry = converters.get(spec["animation"])
            if entry is not None:
                qualified.update(entry["imports"])
            qualified.update(plain_imports(spec))
            continue
        if spec.get("type") == "color" and "valueType" in spec:
            qualified.add("kotlinx.serialization.json.JsonObject")
            qualified.add("com.pycompose.renderer.expressionColor")
        if spec.get("type") == "dp":
            # Kotlin's own conversion is an extension property, so the import
            # is what makes ``model.props.x.dp`` resolve.
            qualified.update(
                {"androidx.compose.ui.unit.dp", "com.pycompose.renderer.number"}
            )
        if spec.get("type") == "number":
            qualified.add("com.pycompose.renderer.number")
        if "indexOf" in spec:
            qualified.update(
                {"com.pycompose.renderer.index", "com.pycompose.renderer.inSlot"}
            )
        if spec.get("type") == "layout":
            qualified.add("com.pycompose.renderer.rememberMeasurePolicy")
        if spec.get("type") == "draw":
            qualified.update(
                {
                    "com.pycompose.renderer.rememberDrawing",
                    "com.pycompose.renderer.generated.paint",
                }
            )
    return qualified
