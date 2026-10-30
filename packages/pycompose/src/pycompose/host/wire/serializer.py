"""Canonical serialization of nodes and versioned snapshots.

The bytes path writes fixed node/envelope keys in canonical order directly,
without a detached wire tree or whole-output string. Generic prop/metadata
objects are ordered by the shared JSON writer. Cost is O(N + V + B) plus object
key sorting; memory is O(B + depth + largest encoded prop/metadata). to_dict is
an explicit O(N + V) detached copy; to_json adapts from UTF-8 bytes.
"""

from __future__ import annotations

from pycompose.errors import IrValidationError
from pycompose.host.wire.model import IRRoot
from pycompose.model.canonical import canonical_json_bytes, thaw_json
from pycompose.model.nodes.expansion import DeferredNode
from pycompose.model.nodes.node import Node
from pycompose.model.nodes.props import JsonValue
from pycompose.model.nodes.reuse import Reuse, SubtreeMemo
from pycompose.model.nodes.traversal import walk_nodes

__all__ = ["node_bytes", "node_to_dict", "to_dict", "to_json", "to_json_bytes"]


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
            if source.slot is not None:
                result["slot"] = source.slot
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


def to_json(snapshot: Node | IRRoot, reuse: Reuse | None = None) -> str:
    """Serialize a snapshot with sorted keys and compact UTF-8 JSON.

    Args:
        snapshot: Node or versioned snapshot.
        reuse: The session's subtree bytes from the last pass, copied in
            where a subtree recurs; None writes everything.

    Returns:
        Deterministic JSON text.
    """
    return to_json_bytes(snapshot, reuse).decode("utf-8")


def node_bytes(node: Node, memo: SubtreeMemo[bytes] | None = None) -> bytes:
    """Serialize one node subtree to canonical UTF-8 bytes.

    Unexpanded Python declarations raise :class:`IrValidationError`.

    Args:
        node: IR node to serialize.
        memo: Subtree bytes to copy in where a subtree recurs; None writes all.

    Returns:
        Deterministic UTF-8 bytes for the subtree.
    """
    output = bytearray()
    _write_node(output, node, memo)
    return bytes(output)


def _write_fields(output: bytearray, node: Node) -> None:
    """Close a node's children, then write its own fields in key order."""
    if node.children:
        output.extend(b"],")
    output.extend(b'"id":')
    output.extend(canonical_json_bytes(node.id))
    output.extend(b',"props":')
    output.extend(canonical_json_bytes(node.props.values))
    if node.slot is not None:
        output.extend(b',"slot":')
        output.extend(canonical_json_bytes(node.slot))
    output.extend(b',"type":')
    output.extend(canonical_json_bytes(node.type))
    output.extend(b"}")


def _write_node(
    output: bytearray, root: Node, memo: SubtreeMemo[bytes] | None = None
) -> None:
    """Stream one node subtree into ``output`` in fixed key order.

    A subtree whose bytes were recorded last pass is copied in whole, and every
    subtree written here is recorded for the next one.

    Args:
        output: Buffer the bytes are appended to.
        root: Subtree to serialize.
        memo: Last pass's subtree bytes; None writes everything.

    Raises:
        IrValidationError: If a Python declaration has not been expanded.
    """
    sibling_counts: list[int] = []
    starts: list[int] = []
    cached: list[bytes | None] = [None]

    def prune(node: Node) -> bool:
        cached[0] = memo.get(node) if memo is not None else None
        return cached[0] is not None

    for node, entering in walk_nodes(root, prune):
        if isinstance(node, DeferredNode):
            raise IrValidationError("expand Python declarations before serialization")
        if entering:
            if sibling_counts:
                if sibling_counts[-1]:
                    output.extend(b",")
                sibling_counts[-1] += 1
            starts.append(len(output))
            reused, cached[0] = cached[0], None
            if reused is not None:
                output.extend(reused)
                sibling_counts.append(-1)
                continue
            output.extend(b'{"children":[' if node.children else b"{")
            sibling_counts.append(0)
        else:
            start = starts.pop()
            if sibling_counts.pop() < 0:
                continue
            _write_fields(output, node)
            if memo is not None:
                memo.put(node, bytes(memoryview(output)[start:]))


def to_json_bytes(snapshot: Node | IRRoot, reuse: Reuse | None = None) -> bytes:
    """Serialize a snapshot to canonical UTF-8 bytes.

    Unexpanded Python declarations raise :class:`IrValidationError`.

    Args:
        snapshot: Node or versioned snapshot.
        reuse: The session's subtree bytes from the last pass, copied in
            where a subtree recurs; None writes everything.

    Returns:
        Deterministic UTF-8 bytes.
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
    if reuse is not None:
        reuse.serialized.start()
    _write_node(output, root, reuse.serialized if reuse is not None else None)
    if isinstance(snapshot, IRRoot):
        output.extend(b',"schemaVersion":')
        output.extend(canonical_json_bytes(snapshot.schema_version))
        output.extend(b',"version":')
        output.extend(canonical_json_bytes(snapshot.version))
        output.extend(b"}")
    return bytes(output)
