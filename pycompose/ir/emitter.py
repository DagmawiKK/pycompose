"""Pure emission from the current State snapshot.

Traversal/reconstruction costs O(N + L), where L counts emitted id bytes. Full
parent-path ids intrinsically make L quadratic for a chain; do not additionally
retain split paths. Already qualified, unchanged branches preserve identity.
"""

from __future__ import annotations

from collections.abc import Mapping

from pycompose.core.expansion import expand_nodes
from pycompose.core.ids import ROOT_ID, IdRegistry, child_id
from pycompose.core.node import Node
from pycompose.core.props import JsonValue
from pycompose.core.traversal import walk_nodes
from pycompose.ir.bindings import lower_bindings
from pycompose.ir.data import lower_data
from pycompose.ir.effects import lower_effects
from pycompose.ir.generated_validators import (
    MIN_SCHEMA_VERSION,
    REGISTRY,
    SCHEMA_VERSION,
)
from pycompose.ir.model import IRRoot
from pycompose.schema.version import require_version
from pycompose.state.state import State

__all__ = ["emit_ir"]


def emit_ir(state: State, schema_version: str) -> IRRoot:
    """Emit a full candidate snapshot without I/O, clock or environment reads.

    Unsupported schemas propagate SchemaError; stable-key collisions propagate
    IrError. Local node ids are stable sibling keys; full-path ids are preserved.
    Pass the result to validate_ir with the boundary's debug/release policy
    before serialization; emission itself does not choose a validation mode.

    Args:
        state: Frozen snapshot from the Store's current composition surface.
        schema_version: Requested wire contract version.

    Returns:
        A versioned IR snapshot.

    """
    require_version(
        schema_version,
        minimum=MIN_SCHEMA_VERSION,
        maximum=SCHEMA_VERSION,
        supported=REGISTRY.supported_schema_versions or (SCHEMA_VERSION,),
    )
    root = _emit_node(expand_nodes(state.root), ROOT_ID, IdRegistry())
    root, bindings = lower_bindings(root)
    metadata: Mapping[str, JsonValue] | None = None
    # Binding contracts, effect requests and app data share one metadata object;
    # their keys never collide, so a merge preserves both declaration orders.
    for member in (
        bindings,
        lower_effects(state.effects),
        lower_data(state.data),
    ):
        if member is not None:
            metadata = {**(metadata or {}), **member}
    return IRRoot(root=root, schema_version=schema_version, metadata=metadata)


def _emit_node(node: Node, node_id: str, ids: IdRegistry) -> Node:
    frames: list[tuple[str, list[Node]]] = []
    result = node
    for source, entering in walk_nodes(node):
        if entering:
            qualified = node_id
            if frames:
                parent_id = frames[-1][0]
                # Full-path ids stay stable; local ids become sibling keys.
                qualified = (
                    source.id
                    if source.id.startswith(f"{parent_id}.")
                    else child_id(parent_id, source.id)
                )
            ids.claim(qualified, node_type=source.type)
            frames.append((qualified, []))
        else:
            qualified, children = frames.pop()
            unchanged = qualified == source.id and all(
                left is right
                for left, right in zip(children, source.children, strict=True)
            )
            result = (
                source
                if unchanged
                else Node(
                    id=qualified,
                    type=source.type,
                    props=source.props,
                    children=tuple(children),
                )
            )
            if frames:
                frames[-1][1].append(result)
    return result
