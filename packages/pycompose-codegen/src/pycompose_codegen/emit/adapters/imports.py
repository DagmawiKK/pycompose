"""The imports a generated adapter needs beyond its component.

Kotlin resolves an extension -- ``.dp``, a renderer helper -- only where it is
imported, so each fact in an entry that makes the adapter call one names the
import with it.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pycompose.contract.registry_vocabulary import STATE_STREAMS
from pycompose_codegen.emit.adapters.state import state_call
from pycompose_codegen.emit.derived_families import property_imports
from pycompose_codegen.emit.state_families import attach_gate


def extra_imports(entry: dict[str, Any]) -> set[str]:
    """List the fully qualified imports an adapter needs beyond its component.

    Args:
        entry: The component's schema entry.

    Returns:
        Import statements' targets, sorted by the caller.
    """
    qualified = _prop_imports(entry.get("props", {}).values())
    if (state := entry.get("state")) is not None and state["kind"] == "properties":
        qualified |= property_imports(state)
    elif state is not None:
        qualified.add(f"com.pycompose.renderer.{state_call(state['kind'])}")
        if state["kind"] in STATE_STREAMS:
            qualified.add("com.pycompose.renderer.publish")
        if attach_gate(state, entry.get("props", {})) is not None:
            # The holder rides the component's modifier, so the extension making
            # that ride callable must be imported where the call is written.
            qualified.add("com.pycompose.renderer.attachTo")
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


def _prop_imports(specs: Iterable[dict[str, Any]]) -> set[str]:
    """The imports a component's props need, beyond the resolvers they name."""
    qualified: set[str] = set()
    for spec in specs:
        if spec.get("type") == "color" and "valueType" in spec:
            qualified.add("kotlinx.serialization.json.JsonObject")
            qualified.add("com.pycompose.renderer.expressionColor")
        if spec.get("type") == "dp":
            # Kotlin's own conversion is an extension property, so the import
            # is what makes ``model.props.x.dp`` resolve.
            qualified.add("androidx.compose.ui.unit.dp")
        if "indexOf" in spec:
            qualified.update(
                {"com.pycompose.renderer.index", "com.pycompose.renderer.inSlot"}
            )
    return qualified
