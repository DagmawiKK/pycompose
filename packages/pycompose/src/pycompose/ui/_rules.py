"""What a component and its subtree must be, checked as a screen is described.

A constructor checks its own node here; a whole snapshot's walk, its ids and
its metadata are the wire's, which checks every node with these same rules.
The rules a prop's value obeys live in :mod:`._props`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import NoReturn, cast

from pycompose.errors import IrValidationError
from pycompose.model.canonical import FrozenJsonValue, check_json
from pycompose.model.catalog.lock import REGISTRY, SCHEMA_VERSION
from pycompose.model.catalog.registry import ComponentDef
from pycompose.model.nodes.node import Node
from pycompose.model.nodes.reuse import SubtreeMemo
from pycompose.model.nodes.target import RenderTarget
from pycompose.model.programs.bindings import BINDINGS_SINCE, is_binding
from pycompose.model.programs.refs import resolve
from pycompose.ui._bound import binding_refusal
from pycompose.ui._props import Intents, validate_prop


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
        host: RenderTarget | None = None,
    ) -> None:
        self.schema_version = schema_version
        # Construction accepts an empty id: the emitter derives one from the
        # node's path before the snapshot boundary, where ids are mandatory.
        self.derived_ids = derived_ids
        # A snapshot bound for a host refuses what it cannot render (ADR-0050).
        self.host = host
        self.intents: Intents = {}
        # The snapshot's programs, by hash, for the props that name them.
        self.programs: Mapping[str, object] = {}
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
            value = self.resolved(props[name], node, name)
            prop = spec.props.get(name)
            if prop is None:
                self.report("unknown prop", node, name)
            if (
                prop.since is not None and not self.available(prop.since)
            ) or not self.values_available(value):
                self.report("prop requires newer schema", node, name)
            if is_binding(value):
                refusal = binding_refusal(value, prop)
                if refusal is not None:
                    self.report(refusal, node, name)
            elif not validate_prop(value, prop, intents=self.intents):
                self.report("invalid prop value", node, name)
        self.child_rules(node, spec)
        return _NodeFrame(
            spec.children.min or 0,
            spec.children.allowed,
            frozenset(spec.slots),
        )

    def resolved(self, value: FrozenJsonValue, node: Node, name: str) -> object:
        try:
            return resolve(value, self.programs)
        except IrValidationError:
            self.report("prop names a program the snapshot lacks", node, name)

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
                if name == "binding" and not self.available(BINDINGS_SINCE):
                    return False
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


def validate_component(node: Node) -> None:
    """Check one component's props and immediate child rules, fail-closed.

    Descendants and global identities are checked by validate_ir after emission.
    Constructors use this seam without repeatedly validating whole subtrees.
    Invalid data propagates IrValidationError with node/prop context.

    Args:
        node: Candidate component node.
    """
    validation = _Validation(derived_ids=True)
    frame = validation.prepare(node)
    unslotted = sum(1 for child in node.children if child.slot is None)
    if unslotted < frame.minimum:
        validation.report("too few children", node)
