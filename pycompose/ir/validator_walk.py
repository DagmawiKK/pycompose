"""Depth-first snapshot walker for IR validation.

The walker carries one :class:`_NodeFrame` per ancestor chain and raises with
node context at the first invalid node: Python validates in debug and tests,
where an invalid snapshot is a bug to report, never a tree to repair. Release
leaves validation to the host's typed parse.

The prop checker lives in ``validator`` and is imported lazily inside the method
that uses it, so ``validator`` can construct this walker without an import cycle.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import NoReturn, cast

from pycompose.contract.catalog import REGISTRY, SCHEMA_VERSION
from pycompose.contract.registry_types import ComponentDef, PropDef
from pycompose.core.node import Node
from pycompose.core.reuse import SubtreeMemo
from pycompose.core.traversal import walk_nodes
from pycompose.errors import IrValidationError
from pycompose.ir.host import Host
from pycompose.utils.json_canonical import FrozenJsonValue, check_json


@dataclass(slots=True)
class _NodeFrame:
    minimum: int
    allow_children: bool
    slots: frozenset[str] = frozenset()
    unslotted: int = 0


class _Validation:
    def __init__(
        self,
        schema_version: str = SCHEMA_VERSION,
        derived_ids: bool = False,
        host: Host | None = None,
    ) -> None:
        self.schema_version = schema_version
        # Construction accepts an empty id: the emitter derives one from the
        # node's path before the snapshot boundary, where ids are mandatory.
        self.derived_ids = derived_ids
        # A snapshot bound for a host refuses what it cannot render (ADR-0050).
        self.host = host
        self.intents: Mapping[str, Mapping[str, PropDef]] = {}
        self.ids: set[str] = set()
        self.path: list[str] = []
        # Clean subtrees from the last pass, with every id each one claims.
        self.memo: SubtreeMemo[tuple[str, ...]] | None = None

    def report(self, message: str, node: Node, prop: str | None = None) -> NoReturn:
        path = tuple(self.path) if self.path else (node.id,)
        raise IrValidationError(
            message, node_id=node.id, node_type=node.type, path=path, prop=prop
        )

    def child_rules(self, node: Node, spec: ComponentDef) -> None:
        """Report direct children or slots a component does not declare.

        Args:
            node: Parent node whose children are checked.
            spec: The parent's registry definition.
        """
        if not spec.children.allowed and any(
            child.slot is None for child in node.children
        ):
            self.report("children are not allowed", node)
        for child in node.children:
            if child.slot is not None and child.slot not in spec.slots:
                self.report("unknown slot", node, child.slot)

    def identity(self, node: Node) -> None:
        if (
            not isinstance(node.id, str)
            or (not node.id and not self.derived_ids)
            or not isinstance(node.type, str)
            or not node.type
        ):
            self.report("invalid node identity", node)
        try:
            check_json(node.id)
            check_json(node.type)
        except IrValidationError:
            self.report("invalid node identity", node)
        if node.id and node.id in self.ids:
            self.report("duplicate node id", node)
        if node.id:
            self.ids.add(node.id)

    def prepare(self, node: Node) -> _NodeFrame:
        from pycompose.ir.validator import validate_prop

        self.identity(node)
        spec = REGISTRY.components.get(node.type)
        if spec is None or (spec.since is not None and not self.available(spec.since)):
            message = (
                "unknown component"
                if spec is None
                else "component requires newer schema"
            )
            self.report(message, node)
        if self.host is not None and self.host.lacks(node.type):
            self.report("the host has no such component; give it a Fallback", node)
        props = cast(Mapping[str, FrozenJsonValue], node.props.values)
        for name, declared in sorted(spec.props.items()):
            if declared.required and name not in props:
                self.report("missing required prop", node, name)
        for name in sorted(node.props):
            prop = spec.props.get(name)
            if prop is None:
                self.report("unknown prop", node, name)
            if (
                prop.since is not None and not self.available(prop.since)
            ) or not self.values_available(props[name]):
                self.report("prop requires newer schema", node, name)
            if not validate_prop(props[name], prop, intents=self.intents):
                self.report("invalid prop value", node, name)
        self.child_rules(node, spec)
        return _NodeFrame(
            spec.children.min or 0,
            spec.children.allowed,
            frozenset(spec.slots),
        )

    def available(self, since: str) -> bool:
        return tuple(map(int, self.schema_version.split("."))) >= tuple(
            map(int, since.split("."))
        )

    def values_available(self, value: object) -> bool:
        pending = [value]
        while pending:
            current = pending.pop()
            if isinstance(current, Mapping):
                name = current.get("type")
                definition = (
                    REGISTRY.value_types.get(name) if isinstance(name, str) else None
                )
                if (
                    definition is not None
                    and "family" in definition
                    and not self.available(str(definition["since"]))
                ):
                    return False
                pending.extend(current.values())
            elif isinstance(current, list | tuple):
                pending.extend(current)
        return True

    def finish(self, node: Node, frame: _NodeFrame) -> None:
        if frame.unslotted < frame.minimum:
            self.report("too few children", node)

    def node(self, root: Node) -> None:
        if root.slot is not None:
            # The root has no parent to fill a slot of.
            self.report("the root cannot fill a slot", root)
        walk = _Walk(self)
        for node, entering in walk_nodes(root, walk.prune):
            if entering:
                walk.enter(node)
            else:
                walk.exit(node)


@dataclass(slots=True)
class _Visit:
    frame: _NodeFrame | None
    reused: tuple[str, ...] | None
    ids: list[str] = field(default_factory=list)


class _Walk:
    """One validation walk; a subtree that was clean last pass is not re-checked.

    Validity of a subtree depends only on itself and the schema version, given
    the parent accepts it, which is still checked here. Its ids are claimed
    again, so a duplicate across subtrees is still found.
    """

    def __init__(self, validation: _Validation) -> None:
        self.validation = validation
        self.visits: list[_Visit] = []
        self.candidate: tuple[str, ...] | None = None

    def prune(self, node: Node) -> bool:
        memo = self.validation.memo
        self.candidate = (
            memo.get(node, self.validation.schema_version) if memo is not None else None
        )
        return self.candidate is not None

    def enter(self, node: Node) -> None:
        validation = self.validation
        validation.path.append(node.id)
        reused, self.candidate = self.candidate, None
        visit = _Visit(None, reused)
        if reused is None:
            visit.frame = validation.prepare(node)
            visit.ids.append(node.id)
        elif validation.ids.isdisjoint(reused):
            validation.ids.update(reused)
            visit.ids.extend(reused)
        else:
            validation.report("duplicate node id", node)
        self.visits.append(visit)

    def exit(self, node: Node) -> None:
        validation = self.validation
        visit = self.visits.pop()
        if visit.frame is not None:
            validation.finish(node, visit.frame)
            # Reaching here means the whole subtree was valid.
            if validation.memo is not None:
                validation.memo.put(node, tuple(visit.ids), validation.schema_version)
        validation.path.pop()
        if self.visits:
            parent = self.visits[-1]
            parent.ids.extend(visit.ids)
            if parent.frame is not None and node.slot is None:
                parent.frame.unslotted += 1
