"""Where a component's children and named slots go."""

from __future__ import annotations

from typing import Any

from pycompose_codegen.emit.adapters.fragments import Fragments
from pycompose_codegen.emit.adapters.policy import camel, simple


def children_argument(children: dict[str, Any], out: Fragments) -> str:
    """The argument the primary children reach, by name: never trailing.

    The schema says which parameter the children reach, and nothing about
    where it sits. Keyed content draws, for each key Compose asks for, the
    subtree Python sent for it: an outgoing key keeps its own while it animates.
    """
    native = children.get("native", "content")
    if children.get("kind") == "keyed":
        out.locals.append(
            "val keyed = context.keyedContent("
            f"model.id, model.props.{camel(children['key'])}, model.children)"
        )
        scope = "this" if children.get("provides") else "null"
        return f"{native} = {{ key -> keyed.Content({scope}, key) }}"
    body, parameter = _slot_body(
        "model.children",
        None,
        children.get("kind"),
        children.get("consume"),
        children.get("provides"),
    )
    prefix = f"{parameter} -> " if parameter is not None else ""
    return f"{native} = {{ {prefix}{body} }}"


def named_slot(slot_name: str, slot: dict[str, Any]) -> str:
    """Render one named slot as a Kotlin argument.

    A nullable Compose parameter takes the slot lambda directly, so an empty
    subtree stays ``null`` and keeps Compose's own default -- passing an empty
    lambda to FilterChip's ``leadingIcon`` would reserve icon space for nothing.
    A non-null parameter always gets a lambda and composes nothing when empty.

    Args:
        slot_name: The declared slot name.
        slot: Its schema entry.

    Returns:
        The ``native = ...`` argument.
    """
    native = slot["native"]
    kind = slot.get("kind", "content")
    consume = slot.get("consume")
    provides = slot.get("provides")
    if provides is not None:
        # The native lambda carries the receiver, so the slot renderer hands
        # that same receiver to scoped children.  A non-null parameter still
        # needs a lambda when the format is empty; the empty lambda preserves
        # the native default.
        call = f'context.slotIn<{simple(provides)}>(model.children, "{slot_name}")'
        if slot.get("nullable"):
            return f"{native} = {call}"
        return f"{native} = {call} ?: {{}}"
    if slot.get("nullable") and consume is None:
        return f'{native} = context.slot(model.children, "{slot_name}")'
    body, parameter = _slot_body("model.children", slot_name, kind, consume)
    prefix = f"{parameter} -> " if parameter is not None else ""
    return f"{native} = {{ {prefix}{body} }}"


def _slot_body(
    nodes: str,
    name: str | None,
    kind: str | None,
    consume: str | None,
    provides: str | None = None,
) -> tuple[str, str | None]:
    """Render the inside of one declared slot's content lambda.

    Args:
        nodes: Kotlin expression for the parent's child list.
        name: Slot name, or None for the primary children.
        kind: ``content`` composes nodes in order; ``items`` lists them lazily.
        consume: Slot scope the adapter consumes on the subtree's behalf.
        provides: Composition scope the pinned lambda carries, handed to the
            children so a scoped child composes under its provider.

    Returns:
        The lambda body, then its parameter name when the slot consumes a scope.
    """
    if kind == "items" and name is None:
        # The primary children may be a window of a longer list (ADR-0043).
        read = (
            f"windowedItems(context, {nodes}.unslotted(), "
            "model.props.itemCount, model.props.itemOffset)"
        )
    elif kind == "items":
        listed = f'{nodes}.inSlot("{name}")'
        read = f"items({listed}, key = {{ it.id }}) {{ context.node(it) }}"
    elif name is None:
        read = (
            f"context.childrenIn(this, {nodes})"
            if provides is not None and consume is None
            else f"context.children({nodes})"
        )
    else:
        # The parameter is non-null, so the lambda always runs and the slot's
        # own lambda is invoked inside it. Evaluating the slot without invoking
        # it would build the subtree and drop it: a component that renders
        # nothing, which is what this line used to do.
        read = f'context.slot({nodes}, "{name}")?.invoke()'
    if consume is None:
        return read, None
    return f"Column(Modifier.padding(padding)) {{ {read} }}", "padding"


def composables(name: str, entry: dict[str, Any]) -> set[str]:
    """List the Compose imports one adapter needs beyond the component itself.

    A flattened content slot is its own dependency: ``Button`` compiles without
    ``Text`` in scope until the slot becomes a real ``Text`` call.

    Args:
        name: The native callable the adapter invokes.
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
