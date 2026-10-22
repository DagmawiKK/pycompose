"""Depth-first snapshot walker for IR validation.

The walker carries one :class:`_NodeFrame` per ancestor chain, accumulates
:class:`ValidationIssue` diagnostics and prunes invalid subtrees; debug mode
raises with node context, release mode rebuilds the tree from the surviving
nodes so regeneration touches only changed nodes and their ancestors.

Result and checker types live in ``validator`` and are imported lazily inside
the methods that use them, so ``validator`` can construct this walker without
an import cycle.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import cast

from pycompose.core.node import Node, Props
from pycompose.core.registry_types import ComponentDef
from pycompose.core.reuse import SubtreeMemo
from pycompose.core.traversal import NodeCycleError, walk_nodes
from pycompose.errors import IrValidationError
from pycompose.ir.generated_validators import REGISTRY, SCHEMA_VERSION
from pycompose.utils.json_canonical import FrozenJsonValue, check_json


@dataclass(slots=True)
class _NodeFrame:
    props: Props
    minimum: int
    allow_children: bool
    slots: frozenset[str] = frozenset()
    children: list[Node] = field(default_factory=list)
    unslotted: int = 0


class _Validation:
    def __init__(
        self,
        debug: bool,
        schema_version: str = SCHEMA_VERSION,
        derived_ids: bool = False,
    ) -> None:
        from pycompose.ir.validator import ValidationIssue

        self.debug = debug
        self.schema_version = schema_version
        # Construction accepts an empty id: the emitter derives one from the
        # node's path before the snapshot boundary, where ids are mandatory.
        self.derived_ids = derived_ids
        self.action_ids: frozenset[str] = frozenset()
        self.issues: list[ValidationIssue] = []
        self.ids: set[str] = set()
        self.path: list[str] = []
        # Clean subtrees from the last pass, with every id each one claims.
        self.memo: SubtreeMemo[tuple[str, ...]] | None = None

    def report(self, message: str, node: Node, prop: str | None = None) -> None:
        from pycompose.ir.validator import ValidationIssue

        path = tuple(self.path) if self.path else (node.id,)
        if self.debug:
            raise IrValidationError(
                message, node_id=node.id, node_type=node.type, path=path, prop=prop
            )
        self.issues.append(ValidationIssue(message, node.id, node.type, path, prop))

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

    def child_allowed(self, parent: _NodeFrame, child: Node) -> bool:
        """Report whether ``parent`` accepts ``child``'s slot.

        Args:
            parent: The enclosing frame with its declared child rules.
            child: The candidate child node.

        Returns:
            True when the child fills a slot the parent declares.
        """
        return _child_allowed(parent, child)

    def identity(self, node: Node) -> bool:
        if (
            not isinstance(node.id, str)
            or (not node.id and not self.derived_ids)
            or not isinstance(node.type, str)
            or not node.type
        ):
            self.report("invalid node identity", node)
            return False
        try:
            check_json(node.id)
            check_json(node.type)
        except IrValidationError:
            self.report("invalid node identity", node)
            return False
        if node.id and node.id in self.ids:
            self.report("duplicate node id", node)
            return False
        if node.id:
            self.ids.add(node.id)
        return True

    def prepare(self, node: Node) -> _NodeFrame | None:
        from pycompose.ir.validator import validate_prop

        if not self.identity(node):
            return None
        spec = REGISTRY.components.get(node.type)
        if spec is None or (spec.since is not None and not self.available(spec.since)):
            message = (
                "unknown component"
                if spec is None
                else "component requires newer schema"
            )
            self.report(message, node)
            return None
        props = cast(Mapping[str, FrozenJsonValue], node.props.values)
        removed: set[str] = set()
        invalid_required = False
        for name, declared in sorted(spec.props.items()):
            if declared.required and name not in props:
                self.report("missing required prop", node, name)
                invalid_required = True
        for name in sorted(node.props):
            prop = spec.props.get(name)
            if prop is None:
                self.report("unknown prop", node, name)
                removed.add(name)
            elif (
                prop.since is not None and not self.available(prop.since)
            ) or not self.values_available(props[name]):
                self.report("prop requires newer schema", node, name)
                removed.add(name)
                invalid_required |= prop.required
            elif not validate_prop(props[name], prop, action_ids=self.action_ids):
                self.report("invalid prop value", node, name)
                removed.add(name)
                invalid_required |= prop.required
        if invalid_required:
            return None
        self.child_rules(node, spec)
        safe_props = node.props
        if removed:
            retained = dict(props)
            for key in removed:
                del retained[key]
            safe_props = Props(retained)
        return _NodeFrame(
            safe_props,
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

    def finish(self, node: Node, frame: _NodeFrame | None) -> Node | None:
        if frame is None:
            return None
        if frame.unslotted < frame.minimum:
            self.report("too few children", node)
            return None
        if (
            frame.props is node.props
            and len(frame.children) == len(node.children)
            and all(
                left is right
                for left, right in zip(frame.children, node.children, strict=True)
            )
        ):
            return node
        return Node(
            id=node.id,
            type=node.type,
            props=frame.props,
            children=tuple(frame.children),
            slot=node.slot,
        )

    def node(self, root: Node) -> Node | None:
        from pycompose.ir.validator import ValidationIssue

        if root.slot is not None:
            # The root has no parent to fill a slot of, and the host rejects a
            # snapshot that says otherwise -- so release mode drops the slot
            # rather than the app's whole first frame.
            self.report("the root cannot fill a slot", root)
            root = replace(root, slot=None)
        walk = _Walk(self)
        try:
            for node, entering in walk_nodes(root, walk.prune):
                if entering:
                    walk.enter(node)
                else:
                    walk.exit(node)
        except NodeCycleError as exc:
            if self.debug:
                raise
            self.issues.append(
                ValidationIssue(
                    "cyclic node graph",
                    str(exc.context["node_id"]),
                    str(exc.context["node_type"]),
                    (*self.path, str(exc.context["node_id"])),
                )
            )
            return None
        return walk.safe


@dataclass(slots=True)
class _Visit:
    frame: _NodeFrame | None
    reused: tuple[str, ...] | None
    issues: int
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
        self.safe: Node | None = None

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
        parent = self.visits[-1].frame if self.visits else None
        enabled = not self.visits or (
            parent is not None and _child_allowed(parent, node)
        )
        visit = _Visit(None, reused, len(validation.issues))
        if not enabled:
            # The parent refuses this node, so nothing beneath it survives.
            visit.reused = None
        elif reused is None:
            visit.frame = validation.prepare(node)
            if visit.frame is not None:
                visit.ids.append(node.id)
        elif validation.ids.isdisjoint(reused):
            validation.ids.update(reused)
            visit.ids.extend(reused)
        else:
            validation.report("duplicate node id", node)
            visit.reused = None
        self.visits.append(visit)

    def exit(self, node: Node) -> None:
        validation = self.validation
        visit = self.visits.pop()
        if visit.reused is not None:
            safe: Node | None = node
        else:
            safe = validation.finish(node, visit.frame)
            clean = safe is node and len(validation.issues) == visit.issues
            if clean and validation.memo is not None:
                validation.memo.put(node, tuple(visit.ids), validation.schema_version)
        validation.path.pop()
        self.safe = safe
        if self.visits:
            parent = self.visits[-1]
            parent.ids.extend(visit.ids)
            if safe is not None and parent.frame is not None:
                parent.frame.children.append(safe)
                if safe.slot is None:
                    parent.frame.unslotted += 1


def _child_allowed(parent: _NodeFrame, child: Node) -> bool:
    """Report whether a frame accepts a child, by the child's slot.

    Args:
        parent: Enclosing frame carrying the declared child rules.
        child: Candidate child node.

    Returns:
        True for primary children of a frame that allows them, or for named
        children of a frame that declares the slot.
    """
    if child.slot is None:
        return parent.allow_children
    return child.slot in parent.slots
