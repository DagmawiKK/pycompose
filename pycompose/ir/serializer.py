"""Canonical serialization of nodes and versioned snapshots."""

from __future__ import annotations

from pycompose.core.node import Node
from pycompose.core.props import JsonValue
from pycompose.ir.model import IRRoot
from pycompose.utils.json_canonical import canonical_json, thaw_json

__all__ = ["node_to_dict", "to_dict", "to_json", "to_json_bytes"]


def node_to_dict(node: Node) -> dict[str, JsonValue]:
    """Convert a node to wire data, omitting children on leaves.

    Args:
        node: IR node to convert.

    Returns:
        Plain JSON values with camelCase prop names.
    """
    result: dict[str, JsonValue] = {
        "id": node.id,
        "props": node.props.to_wire(),
        "type": node.type,
    }
    if node.children:
        result["children"] = [node_to_dict(child) for child in node.children]
    return dict(sorted(result.items()))


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
    return canonical_json(to_dict(snapshot))


def to_json_bytes(snapshot: Node | IRRoot) -> bytes:
    """Serialize a snapshot to canonical UTF-8 bytes.

    Args:
        snapshot: Node or versioned snapshot.

    Returns:
        Deterministic UTF-8 bytes.
    """
    return to_json(snapshot).encode("utf-8")
