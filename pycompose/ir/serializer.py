"""Canonical serialization of nodes and versioned snapshots.

The bytes path writes fixed node/envelope keys in canonical order directly,
without a detached wire tree or whole-output string. Generic prop/metadata
objects are ordered by the shared JSON writer. Cost is O(N + V + B) plus object
key sorting; memory is O(B + depth + largest encoded prop/metadata). to_dict is
an explicit O(N + V) detached copy; to_json adapts from UTF-8 bytes.
"""

from __future__ import annotations

from pycompose.core.expansion import DeferredNode
from pycompose.core.node import Node
from pycompose.core.props import JsonValue
from pycompose.core.traversal import walk_nodes
from pycompose.errors import IrValidationError
from pycompose.ir.model import IRRoot
from pycompose.utils.json_canonical import canonical_json_bytes, thaw_json

__all__ = ["node_to_dict", "to_dict", "to_json", "to_json_bytes"]


def node_to_dict(node: Node) -> dict[str, JsonValue]:
    """Convert a node to wire data, omitting children on leaves.

    Args:
        node: IR node to convert.

    Returns:
        Plain JSON values with camelCase prop names.

    Raises:
        IrValidationError: If a Python declaration has not been expanded.
    """
    frames: list[tuple[dict[str, JsonValue], list[JsonValue]]] = []
    result: dict[str, JsonValue] = {}
    for source, entering in walk_nodes(node):
        if isinstance(source, DeferredNode):
            raise IrValidationError("expand Python declarations before serialization")
        if entering:
            children: list[JsonValue] = []
            result = {}
            if source.children:
                result["children"] = children
            result["id"] = source.id
            result["props"] = source.props.to_wire()
            result["type"] = source.type
            frames.append((result, children))
        else:
            result, _ = frames.pop()
            if frames:
                frames[-1][1].append(result)
    return result


def to_dict(snapshot: Node | IRRoot) -> dict[str, JsonValue]:
    """Convert a snapshot (or standalone node) to wire data.

    Args:
        snapshot: Node or versioned snapshot.

    Returns:
        A plain mapping with camelCase envelope keys.
    """
    if isinstance(snapshot, Node):
        return node_to_dict(snapshot)
    result: dict[str, JsonValue] = {
        "root": node_to_dict(snapshot.root),
        "schemaVersion": snapshot.schema_version,
        "version": snapshot.version,
    }
    if snapshot.metadata is not None:
        result["metadata"] = thaw_json(snapshot.metadata)
    return dict(sorted(result.items()))


def to_json(snapshot: Node | IRRoot) -> str:
    """Serialize a snapshot with sorted keys and compact UTF-8 JSON.

    Args:
        snapshot: Node or versioned snapshot.

    Returns:
        Deterministic JSON text.
    """
    return to_json_bytes(snapshot).decode("utf-8")


def to_json_bytes(snapshot: Node | IRRoot) -> bytes:
    """Serialize a snapshot to canonical UTF-8 bytes.

    Args:
        snapshot: Node or versioned snapshot.

    Returns:
        Deterministic UTF-8 bytes.

    Raises:
        IrValidationError: If a Python declaration has not been expanded.
    """
    output = bytearray()
    root = snapshot if isinstance(snapshot, Node) else snapshot.root
    if isinstance(snapshot, IRRoot):
        output.extend(b"{")
        if snapshot.metadata is not None:
            output.extend(b'"metadata":')
            output.extend(canonical_json_bytes(snapshot.metadata))
            output.extend(b",")
        output.extend(b'"root":')
    sibling_counts: list[int] = []
    for node, entering in walk_nodes(root):
        if isinstance(node, DeferredNode):
            raise IrValidationError("expand Python declarations before serialization")
        if entering:
            if sibling_counts:
                if sibling_counts[-1]:
                    output.extend(b",")
                sibling_counts[-1] += 1
            output.extend(b'{"children":[' if node.children else b"{")
            sibling_counts.append(0)
        else:
            sibling_counts.pop()
            if node.children:
                output.extend(b"],")
            output.extend(b'"id":')
            output.extend(canonical_json_bytes(node.id))
            output.extend(b',"props":')
            output.extend(canonical_json_bytes(node.props.values))
            output.extend(b',"type":')
            output.extend(canonical_json_bytes(node.type))
            output.extend(b"}")
    if isinstance(snapshot, IRRoot):
        output.extend(b',"schemaVersion":')
        output.extend(canonical_json_bytes(snapshot.schema_version))
        output.extend(b',"version":')
        output.extend(canonical_json_bytes(snapshot.version))
        output.extend(b"}")
    return bytes(output)
