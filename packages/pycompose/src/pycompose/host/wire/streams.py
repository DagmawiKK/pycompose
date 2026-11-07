"""Resolve each expression's stream keys to the wire ids the host knows.

An app names a stream's holder by the key it gave the component
(``Stream("nav", "progress")``); the host knows nodes only by their wire ids,
which are compact handles in a release build. Emission records the wire id
each keyed node received, and this pass rewrites the keys once the whole
snapshot is emitted, since a holder may follow the prop that reads it.

An expression may stand as a prop's value, as a binding's target, or as a
modifier's argument; all three are the same wire shape, so all three are read
here. A prop naming the node whose holder a component shares (an expanded
search bar's ``state``) is a key too, and is rewritten the same way.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any, cast

from pycompose.errors import IrValidationError
from pycompose.model.canonical import freeze_json, thaw_json
from pycompose.model.catalog.lock import REGISTRY
from pycompose.model.catalog.modifiers import gesture_streams
from pycompose.model.catalog.vocabulary import holder_streams
from pycompose.model.nodes.node import Node, Props
from pycompose.model.programs.bindings import is_binding
from pycompose.model.programs.expressions import (
    EXPRESSION_KINDS,
    Kind,
    is_expression,
    validate_expression,
)


def has_stream(value: object) -> bool:
    """Whether a prop value carries a stream read anywhere inside it.

    Args:
        value: A prop value, possibly a binding or a modifier.

    Returns:
        True when a ``{"stream": ..., "name": ...}`` node is found.
    """
    if isinstance(value, Mapping):
        return set(value) == {"stream", "name"} or any(
            has_stream(item) for item in value.values()
        )
    if isinstance(value, list | tuple):
        return any(has_stream(item) for item in value)
    return False


def shares_holder(component: str) -> bool:
    """Whether a component names another node whose holder it shares.

    Args:
        component: The component's schema name.

    Returns:
        True when one of its props is such a key, resolved with the streams.
    """
    entry = REGISTRY.components.get(component)
    return bool(entry is not None and entry.shared)


def resolve_streams(root: Node, keyed: Mapping[str, Sequence[str]]) -> Node:
    """Rewrite every expression's stream keys to its holder's wire id.

    A key naming no node, or more than one, raises ``IrValidationError``.

    Args:
        root: The emitted snapshot root.
        keyed: The wire ids each key was given during emission.

    Returns:
        The root, rebuilt along the paths to nodes carrying expressions.
    """

    def wire_id(key: str, node: Node, prop: str) -> str:
        found = keyed.get(key, ())
        if len(found) != 1:
            why = "no component" if not found else f"{len(found)} components"
            raise IrValidationError(
                f"stream key {key!r} names {why}", node_id=node.id, prop=prop
            )
        return found[0]

    def resolve(value: Any, owner: Node, prop: str) -> Any:
        if isinstance(value, dict):
            if set(value) == {"stream", "name"}:
                return {**value, "stream": wire_id(value["stream"], owner, prop)}
            return {key: resolve(item, owner, prop) for key, item in value.items()}
        if isinstance(value, list):
            return [resolve(item, owner, prop) for item in value]
        return value

    def walk(node: Node) -> Node:
        children = tuple(walk(child) for child in node.children)
        entry = REGISTRY.components.get(node.type)
        shared = (entry.shared if entry is not None else None) or {}
        props = {
            name: wire_id(value, node, name)
            if name in shared and isinstance(value, str)
            else freeze_json(resolve(thaw_json(value), node, name))
            if has_stream(value)
            else value
            for name, value in node.props.values.items()
        }
        changed = any(
            new is not old for new, old in zip(children, node.children, strict=True)
        ) or any(props[name] is not value for name, value in node.props.values.items())
        if not changed:
            return node
        return Node(
            id=node.id,
            type=node.type,
            props=Props(props),
            children=children,
            slot=node.slot,
        )

    return walk(root)


def stream_problems(root: Node) -> list[tuple[Node, str, str]]:
    """Find streams an expression reads that its holder does not expose.

    Args:
        root: A resolved snapshot root.

    Returns:
        (node, prop, message) for each stream naming no node, or a node whose
        state family does not expose it.
    """
    nodes: dict[str, Node] = {}
    pending = [root]
    while pending:
        node = pending.pop()
        nodes[node.id] = node
        pending.extend(node.children)
    problems = []
    for node in nodes.values():
        for label, expression, kind in _sites(node):
            for holder, stream in validate_expression(expression, kind):
                target = nodes.get(holder)
                if target is None or stream not in exposed(target):
                    problems.append(
                        (
                            node,
                            label,
                            f"stream {stream!r} names no holder exposing it",
                        )
                    )
    return problems


def exposed(node: Node) -> set[str]:
    """The streams a node exposes: its holder's, and those of each gesture it wears.

    Args:
        node: A snapshot node.

    Returns:
        The stream names expressions may read from it.
    """
    spec = REGISTRY.components.get(node.type)
    state = spec.state if spec is not None else None
    held = (state.derived or {}).get("holder") if state is not None else None
    names = set(holder_streams(state.kind, held)) if state is not None else set()
    modifier = node.props.values.get("modifier")
    operations = modifier.get("operations") if isinstance(modifier, Mapping) else None
    gestures = gesture_streams(REGISTRY.derived_modifiers)
    for operation in operations if isinstance(operations, list | tuple) else ():
        if isinstance(operation, Mapping):
            names.update(gestures.get(str(operation.get("type")), ()))
    return names


def _sites(node: Node) -> Iterator[tuple[str, Mapping[str, Any], Kind]]:
    """Each expression a node carries, the label to report, and the kind it gives."""
    declared = REGISTRY.components.get(node.type)
    for prop, value in node.props.values.items():
        if prop == "modifier":
            yield from _modifier_sites(value)
            continue
        rule = declared.props.get(prop) if declared is not None else None
        kind = EXPRESSION_KINDS.get(rule.type if rule is not None else "")
        if kind is None:
            continue
        for expression in _expressions(value):
            yield prop, expression, kind


def _modifier_sites(
    value: object,
) -> Iterator[tuple[str, Mapping[str, Any], Kind]]:
    """Each expression a modifier's arguments carry, labelled by operation and prop."""
    operations = value.get("operations") if isinstance(value, Mapping) else None
    if not isinstance(operations, list | tuple):
        return
    for operation in operations:
        if not isinstance(operation, Mapping):
            continue
        name = str(operation.get("type"))
        rules = REGISTRY.modifiers.get(name, {})
        for key, item in operation.items():
            if key == "type":
                continue
            rule = rules.get(key)
            kind = EXPRESSION_KINDS.get(rule.type if rule is not None else "")
            if kind is None:
                continue
            for expression in _expressions(item):
                yield f"{name}.{key}", expression, kind


def _expressions(value: object) -> Iterator[Mapping[str, Any]]:
    """Every expression a value states, a binding read through its target."""
    if not isinstance(value, Mapping):
        return
    if is_expression(value):
        yield cast("Mapping[str, Any]", thaw_json(value))
    elif is_binding(value):
        yield from _expressions(value.get("target"))
