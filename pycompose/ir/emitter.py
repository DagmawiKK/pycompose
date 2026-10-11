"""Pure emission from the current State snapshot."""

from __future__ import annotations

from dataclasses import replace

from pycompose.core.ids import ROOT_ID, IdRegistry, child_id
from pycompose.core.node import Node
from pycompose.ir.generated_validators import MIN_SCHEMA_VERSION, SCHEMA_VERSION
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
    require_version(schema_version, minimum=MIN_SCHEMA_VERSION, maximum=SCHEMA_VERSION)
    root = _emit_node(state.root, ROOT_ID, IdRegistry())
    return IRRoot(root=root, schema_version=schema_version)


def _emit_node(node: Node, node_id: str, ids: IdRegistry) -> Node:
    ids.claim(node_id, node_type=node.type)
    children: list[Node] = []
    for child in node.children:
        # Explicit full-path ids stay stable; local ids become stable sibling keys.
        qualified = (
            child.id
            if child.id.startswith(f"{node_id}.")
            else child_id(node_id, child.id)
        )
        children.append(_emit_node(child, qualified, ids))
    return replace(node, id=node_id, children=tuple(children))
