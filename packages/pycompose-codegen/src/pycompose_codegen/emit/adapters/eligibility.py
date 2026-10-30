"""Which components get a generated adapter.

An entry qualifies when every prop renders without a human decision and every
child path comes from the closed slot vocabulary; the rest keep a hand-written
adapter in ``BuiltinComponents.kt``.
"""

from __future__ import annotations

from typing import Any

from pycompose.contract.registry_types import CONSUMERS, SLOT_KINDS
from pycompose_codegen.emit.adapters.policy import DECODED, MECHANICAL
from pycompose_codegen.emit.state_families import (
    STATE_CONSTRUCTOR_PROPS,
    attach_gate,
    property_props,
)


def is_mechanical(entry: dict[str, Any]) -> bool:
    """Report whether a component's adapter can be derived from its schema.

    Args:
        entry: The component's schema entry.

    Returns:
        True when every prop renders without a human decision.
    """
    if entry.get("adapter") == "manual":
        return False
    if entry.get("wrapper"):
        # Text and Image hand off to ResourceText / ResourceImage, which load
        # their content off the Compose thread and report their own diagnostics.
        # The call site is mechanical; what it delegates to is not.
        return False
    if not _declared_slots(entry):
        return False
    held = held_props(entry)
    return all(
        prop in held or _mechanical_prop(spec)
        for prop, spec in entry.get("props", {}).items()
    )


def held_props(entry: dict[str, Any]) -> set[str]:
    """Collect the props a state holder consumes instead of rendering.

    Args:
        entry: The component's schema entry.

    Returns:
        Names the holder fills or observes, so they never reach a native
        parameter and their wire type need not be renderable by an adapter.
    """
    state = entry.get("state")
    if not isinstance(state, dict):
        return set()
    if state.get("kind") == "properties":
        return set(property_props(state))
    held = {
        name for key in ("value", "report") if isinstance(name := state.get(key), str)
    }
    kind = state.get("kind")
    if isinstance(kind, str):
        held.update(STATE_CONSTRUCTOR_PROPS.get(kind, ()))
        gate = attach_gate(state, entry.get("props", {}))
        if gate is not None:
            held.add(gate)
    return held


def _declared_slots(entry: dict[str, Any]) -> bool:
    """Report whether every child path is drawn from the closed slot vocabulary.

    Args:
        entry: The component's schema entry.

    Returns:
        True when the primary children and every named slot use a kind and a
        consumer this generator renders.
    """
    if any(slot.get("host") for slot in entry.get("slots", {}).values()):
        return False
    children = entry.get("children", {})
    scoped = not ("provides" in children and children.get("consume") is not None)
    return (
        children.get("kind") in {None, *SLOT_KINDS}
        and children.get("consume") in {None, *CONSUMERS}
        and scoped
        and all(
            slot.get("kind", "content") in SLOT_KINDS
            and slot.get("consume") in {None, *CONSUMERS}
            and not (slot.get("provides") and slot.get("consume"))
            and not (slot.get("provides") and slot.get("kind", "content") != "content")
            for slot in entry.get("slots", {}).values()
        )
    )


def _mechanical_prop(spec: dict[str, Any]) -> bool:
    """Report whether one prop renders without a human decision.

    Args:
        spec: The prop's schema entry.

    Returns:
        True when the adapter can resolve it from its declared type.
    """
    if "valueType" in spec:
        if spec["type"] == "value" and (
            spec.get("required") or "nativeDefault" in spec
        ):
            return True
        # A colour prop takes its tagged value or an expression over streams,
        # and falls back to its declared colour when absent.
        return spec.get("type") == "color"
    if spec.get("type") in MECHANICAL:
        return True
    # A dp prop carries a plain number and needs no decoder, but only a prop
    # with some default to fall back to can be rendered at all.
    if spec.get("type") == "dp" and _dp_renderable(spec):
        return True
    if spec.get("type") == "resource":
        # A resource loads off the Compose thread with its own diagnostics, so
        # only a wrapper (Text's, Image's) renders one; see WRAPPERS.
        return False
    # Decodable types need a named resolver; without one they cannot be
    # rendered at all rather than rendered wrongly.
    return spec.get("type") in DECODED and bool(spec.get("decode"))


def _dp_renderable(spec: dict[str, Any]) -> bool:
    """Report whether a dp prop has something to fall back on.

    A dp prop is always passed when it is required or carries a literal model
    default, and an optional one names its pinned default in ``nativeDefault``.
    Without either, a stated value would ride the wire and never reach Compose.

    Args:
        spec: The prop's schema entry.

    Returns:
        True when the adapter can render the prop without a decision.
    """
    return bool(spec.get("required") or "default" in spec or "nativeDefault" in spec)
