"""Resolve each expression's stream keys to the wire ids the host knows.

An app names a stream's holder by the key it gave the component
(``Stream("nav", "progress")``); the host knows nodes only by their wire ids,
which are compact handles in a release build. Emission records the wire id
each keyed node received, and this pass rewrites the keys once the whole
snapshot is emitted, since a holder may follow the prop that reads it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pycompose.contract.registry_vocabulary import STATE_STREAMS
from pycompose.core.expressions import validate_expression
from pycompose.core.node import Node, Props
from pycompose.errors import IrValidationError
from pycompose.utils.json_canonical import freeze_json, thaw_json


def is_expression(value: object) -> bool:
    """Whether a prop value is an expression's wire object.

    Args:
        value: A prop value.

    Returns:
        True for ``{"type": "expression", ...}``.
    """
    return isinstance(value, Mapping) and value.get("type") == "expression"


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

    def resolve(node: Any, owner: Node, prop: str) -> Any:
        if isinstance(node, dict):
            if set(node) == {"stream", "name"}:
                return {**node, "stream": wire_id(node["stream"], owner, prop)}
            return {key: resolve(value, owner, prop) for key, value in node.items()}
        if isinstance(node, list):
            return [resolve(value, owner, prop) for value in node]
        return node

    def walk(node: Node) -> Node:
        children = tuple(walk(child) for child in node.children)
        props = {
            name: freeze_json(resolve(thaw_json(value), node, name))
            if is_expression(value)
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
    from pycompose.ir.generated_validators import REGISTRY

    nodes: dict[str, Node] = {}
    pending = [root]
    while pending:
        node = pending.pop()
        nodes[node.id] = node
        pending.extend(node.children)
    problems = []
    for node in nodes.values():
        for prop, value in node.props.values.items():
            if not is_expression(value):
                continue
            for holder, stream in validate_expression(thaw_json(value), "color"):
                target = nodes.get(holder)
                spec = REGISTRY.components.get(target.type) if target else None
                kind = spec.state.kind if spec is not None and spec.state else None
                if stream not in STATE_STREAMS.get(kind or "", ()):
                    problems.append(
                        (node, prop, f"stream {stream!r} names no holder exposing it")
                    )
    return problems
