"""Pure emission from the current State snapshot.

Traversal/reconstruction costs O(N + L), where L counts emitted id bytes. Full
parent-path ids intrinsically make L quadratic for a chain; do not additionally
retain split paths. Already qualified, unchanged branches preserve identity.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from pycompose.core.expansion import expand_nodes
from pycompose.core.ids import Handles, IdRegistry, sibling_keys
from pycompose.core.node import Node
from pycompose.core.props import JsonValue
from pycompose.core.reuse import Reuse, SubtreeMemo
from pycompose.core.traversal import walk_nodes
from pycompose.errors import IrValidationError
from pycompose.ir.bindings import lower_props, record
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


def emit_ir(state: State, schema_version: str, reuse: Reuse | None = None) -> IRRoot:
    """Emit a full candidate snapshot without I/O, clock or environment reads.

    Unsupported schemas propagate SchemaError; stable-key collisions propagate
    IrError. Local node ids are stable sibling keys; full-path ids are preserved.
    Pass the result to validate_ir with the boundary's debug/release policy
    before serialization; emission itself does not choose a validation mode.

    Args:
        state: Frozen snapshot from the Store's current composition surface.
        schema_version: Requested wire contract version.
        reuse: The session's results from the previous publish, reused where
            a subtree is unchanged; None emits everything afresh.

    Returns:
        A versioned IR snapshot.

    """
    require_version(
        schema_version,
        minimum=MIN_SCHEMA_VERSION,
        maximum=SCHEMA_VERSION,
        supported=REGISTRY.supported_schema_versions or (SCHEMA_VERSION,),
    )
    if reuse is not None:
        reuse.emitted.start()
    handles = reuse.handles if reuse else Handles(compact=False)
    ids = IdRegistry()
    root, contracts = _emit_node(
        expand_nodes(state.root, reuse.expansion if reuse else None),
        _Emission(ids, handles, reuse.emitted if reuse else None),
    )
    handles.retain(ids)
    bindings = (
        cast("Mapping[str, JsonValue]", {"actionBindings": contracts})
        if contracts
        else None
    )
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


@dataclass(frozen=True, slots=True)
class _Emitted:
    """One emitted subtree: its node, every (id, type) in it, and its bindings."""

    node: Node
    ids: tuple[tuple[str, str], ...]
    contracts: tuple[tuple[str, object], ...]


@dataclass(slots=True)
class _Frame:
    qualified: str
    reused: _Emitted | None
    context: object
    keys: tuple[tuple[str | int, bool], ...] = ()
    children: list[Node] = field(default_factory=list)
    ids: list[tuple[str, str]] = field(default_factory=list)
    contracts: list[tuple[str, object]] = field(default_factory=list)


class _Emission:
    """Qualify ids and lower bindings in one walk, reusing unchanged subtrees.

    A subtree's emission depends on the subtree and on where it hangs: its
    parent's qualified id and its key among its siblings. Both form the memo
    context, so a reused subtree is exactly what a fresh walk would produce,
    and its ids and binding contracts are replayed, not redone.
    """

    def __init__(
        self, ids: IdRegistry, handles: Handles, memo: SubtreeMemo[_Emitted] | None
    ) -> None:
        self.ids = ids
        self.handles = handles
        self.memo = memo
        self.contracts: dict[str, object] = {}
        self.frames: list[_Frame] = []
        self.candidate: _Emitted | None = None

    def key(self) -> tuple[str | int, bool]:
        parent = self.frames[-1]
        return parent.keys[len(parent.children)]

    def context(self) -> object:
        return (self.frames[-1].qualified, self.key()[0])

    def prune(self, source: Node) -> bool:
        self.candidate = (
            self.memo.get(source, self.context())
            if self.memo is not None and self.frames
            else None
        )
        return self.candidate is not None

    def enter(self, source: Node) -> None:
        reused, self.candidate = self.candidate, None
        context = self.context() if self.frames else None
        if reused is not None:
            self.frames.append(_Frame(reused.node.id, reused, context))
            return
        qualified = self.qualify(source)
        self.ids.claim(qualified, node_type=source.type)
        keys = sibling_keys(source.children)
        self.frames.append(_Frame(qualified, None, context, keys))

    def qualify(self, source: Node) -> str:
        if not self.frames:
            return self.handles.root
        parent = self.frames[-1].qualified
        key, repeated = self.key()
        if not source.id and (repeated or not source.site) and _addressable(source):
            # Order is all that tells these apart, and a reorder would hand
            # one element's native state and bindings to another.
            raise IrValidationError(
                "a component with bindings declared in a loop needs an explicit id",
                node_type=source.type,
                site=source.site,
            )
        return self.handles.child(parent, key)

    def exit(self, source: Node) -> Node:
        frame = self.frames.pop()
        emitted = frame.reused
        if emitted is not None:
            for node_id, node_type in emitted.ids:
                self.ids.claim(node_id, node_type=node_type)
            for key, wire in emitted.contracts:
                record(self.contracts, key, wire)
        else:
            emitted = self.build(source, frame)
            if self.memo is not None and self.frames:
                self.memo.put(source, emitted, frame.context)
        if self.frames:
            parent = self.frames[-1]
            parent.children.append(emitted.node)
            parent.ids.extend(emitted.ids)
            parent.contracts.extend(emitted.contracts)
        return emitted.node

    def build(self, source: Node, frame: _Frame) -> _Emitted:
        def declare(key: str, wire: object) -> None:
            record(self.contracts, key, wire)
            frame.contracts.append((key, wire))

        props = lower_props(source.props, declare)
        unchanged = (
            frame.qualified == source.id
            and props is source.props
            and all(
                left is right
                for left, right in zip(frame.children, source.children, strict=True)
            )
        )
        node = (
            source
            if unchanged
            else Node(
                id=frame.qualified,
                type=source.type,
                props=props,
                children=tuple(frame.children),
                slot=source.slot,
            )
        )
        return _Emitted(
            node, ((frame.qualified, source.type), *frame.ids), tuple(frame.contracts)
        )


def _emit_node(root: Node, emission: _Emission) -> tuple[Node, dict[str, object]]:
    result = root
    for source, entering in walk_nodes(root, emission.prune):
        if entering:
            emission.enter(source)
        else:
            result = emission.exit(source)
    return result, emission.contracts


def _addressable(node: Node) -> bool:
    """Report whether anything can name this node.

    An action prop -- bound or a raw action id -- or a modifier operation
    carrying one makes the node addressable: native fast values and effect
    targets key on its id, so a positional identity would reattach state to
    the wrong element after a list reorder.

    Args:
        node: Candidate node with no id of its own.

    Returns:
        ``True`` when the node must keep an explicit id.
    """
    definition = REGISTRY.components.get(node.type)
    if definition is not None and any(
        node.props.get(name) is not None
        for name, rule in definition.props.items()
        if rule.type == "actionId"
    ):
        return True
    modifier = node.props.get("modifier")
    if isinstance(modifier, Mapping):
        operations = modifier.get("operations", ())
        if isinstance(operations, list | tuple):
            for operation in operations:
                if not isinstance(operation, Mapping):
                    continue
                props = REGISTRY.modifiers.get(str(operation.get("type")))
                if props is not None and any(
                    operation.get(name) is not None
                    for name, rule in props.items()
                    if rule.type == "actionId"
                ):
                    return True
    return False
