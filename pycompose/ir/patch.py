"""Value diffing of published snapshots into byte-stable pull envelopes.

ADR-0018: the publish layer keeps the last-published root and answers the
host's pull with either the full snapshot or a patch envelope diffed against
the base the host declares it still holds. This module is the pure half of
that layer -- the diff, the two op shapes it may emit, and canonical envelope
bytes. It owns no state and never imports the bridge; the serial window that
decides full-versus-patch sits with the bridge that answers pulls.

Diffing is a value walk, not a pointer trick: every ``f(State)`` pass rebuilds
nodes, so unchanged branches are recognized by identity only when a caller
reuses them. Cost is O(compared nodes + changed props) with identity shortcuts;
envelope bytes are O(ops + changed subtree). A removed prop or a changed type,
slot, or children shape ships the topmost such subtree whole -- the v1 op set
has no finer structural operation (ADR-0018 decision 2).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pycompose.core.node import Node
from pycompose.core.props import JsonValue
from pycompose.core.reuse import Reuse
from pycompose.ir.model import IRRoot
from pycompose.ir.serializer import node_bytes
from pycompose.utils.json_canonical import FrozenJsonValue, canonical_json_bytes

__all__ = [
    "PatchOp",
    "ReplaceSubtree",
    "SetProp",
    "diff_nodes",
    "full_bytes",
    "patch_bytes",
]


@dataclass(frozen=True, slots=True)
class SetProp:
    """Replace one prop value on one node.

    Attributes:
        id: Node id carrying the change.
        at: Child indices from the root to that node.
        prop: The node's ``camelCase`` prop name.
        value: The node's new prop value, as emitted.
    """

    id: str
    at: tuple[int, ...]
    prop: str
    value: JsonValue | FrozenJsonValue


@dataclass(frozen=True, slots=True)
class ReplaceSubtree:
    """Replace the whole subtree rooted at one node.

    Attributes:
        id: Node id of the topmost changed subtree.
        at: Child indices from the root to that node.
        payload: That subtree exactly as emitted, never a partial patch of it.
    """

    id: str
    at: tuple[int, ...]
    payload: Node


PatchOp = SetProp | ReplaceSubtree


def diff_nodes(base: Node, new: Node) -> tuple[PatchOp, ...]:
    """Diff two emitted roots into ordered ops, empty when they are equal.

    Ops are deterministic: depth-first in the new tree, a node's ops before
    its children's, siblings left to right, prop names sorted. Nothing below a
    replaced subtree is diffed. Each op locates its node by child indices, which
    are the same in both trees along any path the diff descends, so the host
    finds it without reading meaning into ids.

    Args:
        base: The root the host declared it still holds.
        new: The root being published.

    Returns:
        The ops that turn ``base`` into ``new``.
    """
    ops: list[PatchOp] = []
    pending: list[tuple[Node, Node, tuple[int, ...]]] = [(base, new, ())]
    while pending:
        old, candidate, at = pending.pop()
        if old is candidate:
            continue
        if not _compatible(old, candidate):
            ops.append(ReplaceSubtree(id=candidate.id, at=at, payload=candidate))
            continue
        previous = old.props.values
        current = candidate.props.values
        if previous != current:
            if previous.keys() - current.keys():
                # A prop vanished; no op can remove one, so the node ships whole.
                ops.append(ReplaceSubtree(id=candidate.id, at=at, payload=candidate))
                continue
            for name in sorted(current):
                value = current[name]
                if name not in previous or previous[name] != value:
                    ops.append(SetProp(id=candidate.id, at=at, prop=name, value=value))
        # Queued reversed so pop() walks siblings left to right.
        pending.extend(
            (left, right, (*at, index))
            for index, (left, right) in reversed(
                list(enumerate(zip(old.children, candidate.children, strict=True)))
            )
        )
    return tuple(ops)


def _compatible(old: Node, new: Node) -> bool:
    """Report whether two nodes may diff prop-by-prop at the same position.

    A child pair is queued only after its parent's shape check proved the ids
    at that position equal, so comparing ids here only matters for two roots
    that do not share one.

    Args:
        old: Node from the base tree.
        new: Node from the published tree.

    Returns:
        ``True`` when only props may differ.
    """
    if old.id != new.id:
        return False
    if (
        old.type != new.type
        or old.slot != new.slot
        or len(old.children) != len(new.children)
    ):
        return False
    return all(
        left.id == right.id
        for left, right in zip(old.children, new.children, strict=True)
    )


def full_bytes(
    root: IRRoot, *, serial: int, surface: str, reuse: Reuse | None = None
) -> bytes:
    """Serialize the pull result carrying the whole snapshot.

    The result is the snapshot's own envelope plus ``kind`` and ``serial``, so
    every existing snapshot reader keeps working on it unchanged.

    Args:
        root: The snapshot being published.
        serial: The serial this content is published under.
        surface: The surface the snapshot renders on.
        reuse: The session's subtree bytes, copied in where a subtree recurs.

    Returns:
        Canonical UTF-8 bytes.
    """
    output = bytearray(b'{"kind":"full"')
    if root.metadata is not None:
        output.extend(b',"metadata":')
        output.extend(canonical_json_bytes(root.metadata))
    output.extend(b',"root":')
    output.extend(
        node_bytes(root.root, reuse.serialized if reuse is not None else None)
    )
    output.extend(b',"schemaVersion":')
    output.extend(canonical_json_bytes(root.schema_version))
    output.extend(b',"serial":')
    output.extend(str(serial).encode())
    output.extend(b',"surface":')
    output.extend(canonical_json_bytes(surface))
    output.extend(b',"version":')
    output.extend(canonical_json_bytes(root.version))
    output.extend(b"}")
    return bytes(output)


def patch_bytes(
    root: IRRoot,
    ops: Sequence[PatchOp],
    *,
    base_serial: int,
    serial: int,
    surface: str,
    base: IRRoot | None = None,
) -> bytes:
    """Serialize the pull result carrying ops against the host's base.

    Metadata (intent contracts, effects, echoes, app data) belongs to the
    snapshot that carried it, so every envelope states it (ADR-0018 decision 3),
    except app data equal to the base's: that is not sent again but named in
    ``keep``, for the host to carry over. Effects belong to one transition and
    always travel whole.

    Args:
        root: The snapshot the ops lead to; supplies version and metadata.
        ops: Ops from :func:`diff_nodes`, in their deterministic order.
        base_serial: The serial the host declared it still holds.
        serial: The serial this content is published under.
        surface: The surface the snapshot renders on.
        base: The snapshot the host holds, so unchanged app data is kept
            rather than sent; None sends the metadata whole.

    Returns:
        Canonical UTF-8 bytes.
    """
    metadata: Mapping[str, object] | None = root.metadata
    keep: list[str] = []
    if base is not None:
        held = (base.metadata or {}).get("data")
        if metadata is not None and held is not None and metadata.get("data") == held:
            metadata = {k: v for k, v in metadata.items() if k != "data"} or None
            keep.append("data")
    output = bytearray(b'{"baseSerial":')
    output.extend(str(base_serial).encode())
    if keep:
        output.extend(b',"keep":')
        output.extend(canonical_json_bytes(keep))
    output.extend(b',"kind":"patch"')
    if metadata is not None:
        output.extend(b',"metadata":')
        output.extend(canonical_json_bytes(metadata))
    output.extend(b',"ops":[')
    for index, op in enumerate(ops):
        if index:
            output.extend(b",")
        output.extend(b'{"at":')
        output.extend(canonical_json_bytes(list(op.at)))
        output.extend(b',"id":')
        output.extend(canonical_json_bytes(op.id))
        if isinstance(op, SetProp):
            output.extend(b',"op":"setProp","prop":')
            output.extend(canonical_json_bytes(op.prop))
            output.extend(b',"value":')
            output.extend(canonical_json_bytes(op.value))
        else:
            output.extend(b',"op":"replaceSubtree","payload":')
            output.extend(node_bytes(op.payload))
        output.extend(b"}")
    output.extend(b'],"schemaVersion":')
    output.extend(canonical_json_bytes(root.schema_version))
    output.extend(b',"serial":')
    output.extend(str(serial).encode())
    output.extend(b',"surface":')
    output.extend(canonical_json_bytes(surface))
    output.extend(b',"version":')
    output.extend(canonical_json_bytes(root.version))
    output.extend(b"}")
    return bytes(output)
