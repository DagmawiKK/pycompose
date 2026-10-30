"""What a component and its props must be, checked as a screen is described.

A constructor checks its own node here; a whole snapshot's walk, its ids and
its metadata are the wire's, which checks every node with these same rules.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import NoReturn, cast

from pycompose.errors import IrValidationError
from pycompose.model.canonical import FrozenJsonValue, check_json
from pycompose.model.catalog.lock import REGISTRY, SCHEMA_VERSION
from pycompose.model.catalog.registry import ComponentDef, PropDef
from pycompose.model.nodes.node import Node
from pycompose.model.nodes.resources import valid_resource
from pycompose.model.nodes.reuse import SubtreeMemo
from pycompose.model.nodes.target import RenderTarget
from pycompose.model.nodes.values import (
    validate_bounds,
    validate_number,
    validate_value,
)
from pycompose.ui.intents import BoundIntent, valid_intent

_LONG = range(-(2**63), 2**63)
"""The integers a host can hold: a Kotlin Long."""


def _is_long(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value in _LONG


_TYPE_CHECKS: dict[str, Callable[[object, PropDef], bool]] = {
    "string": lambda value, _: isinstance(value, str),
    "resource": lambda value, prop: valid_resource(value, prop.values),
    # A colour of a value family crosses the wire only as its tagged object.
    "color": lambda value, prop: isinstance(value, str) and prop.value_type is None,
    "boolean": lambda value, _: isinstance(value, bool),
    "integer": lambda value, _: _is_long(value),
    "durationMs": lambda value, _: _is_long(value),
    "number": lambda value, _: isinstance(value, int | float)
    and not isinstance(value, bool),
    "dp": lambda value, _: _is_native_float(value),
    "modifier": lambda value, _: isinstance(value, Mapping),
    # A named constant of a value family crosses the wire only tagged.
    "enum": lambda value, prop: isinstance(value, str)
    and prop.value_type is None
    and value in prop.values,
    "actionId": lambda value, _: isinstance(value, BoundIntent)
    or (isinstance(value, str) and value in REGISTRY.actions),
}


Intents = Mapping[str, Mapping[str, PropDef]]
"""Each stated handler's payload contract, by handler id."""


def validate_prop(
    value: object, prop: PropDef, *, intents: Intents | None = None
) -> bool:
    """Check a JSON value against a generated prop or payload definition.

    Args:
        value: Candidate value, including frozen JSON containers.
        prop: Definition from the component registry.
        intents: The snapshot's intent contracts, for action props.

    Returns:
        Whether the type, bounds and registry references are valid.
    """
    if value is None:
        return prop.nullable
    check = _TYPE_CHECKS.get(prop.type)
    if isinstance(value, Mapping) and (
        prop.value_type is not None or prop.type == "actionId"
    ):
        # An action prop's object is an intent; any other object is a value.
        return (
            valid_intent(value, intents or {})
            if prop.type == "actionId"
            else _valid_value(value, prop)
        )
    if check is None or not check(value, prop):
        return False
    try:
        if prop.type == "modifier":
            validate_modifier(value, intents=intents)
        else:
            check_json(value)
    except IrValidationError:
        return False
    if isinstance(value, int | float):
        return (prop.minimum is None or value >= prop.minimum) and (
            prop.maximum is None or value <= prop.maximum
        )
    return True


def _is_native_float(value: object) -> bool:
    try:
        validate_number(value, {"type": "float"})
    except IrValidationError:
        return False
    return True


def _valid_value(value: object, prop: PropDef) -> bool:
    try:
        validate_value(value, str(prop.value_type), REGISTRY.value_types)
        validate_bounds(value, prop.minimum, prop.maximum)
    except IrValidationError:
        return False
    return True


def validate_modifier(value: object, *, intents: Intents | None = None) -> None:
    """Validate ordered operations using generated modifier definitions.

    A modifier is an object holding its operations, the only shape Python
    writes; any other is refused. Invalid JSON propagates IrValidationError
    from the shared checker.

    Args:
        value: Ordinary or frozen modifier object.
        intents: The snapshot's intent contracts, for click actions.

    Raises:
        IrValidationError: If operations, props or action references are invalid.
    """
    check_json(value)
    if not isinstance(value, Mapping):
        raise IrValidationError("modifier must be an object")
    if set(value) != {"operations"}:
        raise IrValidationError("modifier must hold exactly its operations")
    operations = value["operations"]
    if not isinstance(operations, list | tuple):
        raise IrValidationError("modifier operations must be an array")
    for operation in operations:
        if not isinstance(operation, Mapping) or not isinstance(
            operation.get("type"), str
        ):
            raise IrValidationError("invalid modifier operation")
        name = operation["type"]
        spec = REGISTRY.modifiers.get(name)
        if spec is None:
            raise IrValidationError("unknown modifier operation", modifier=name)
        for key, prop in spec.items():
            if prop.required and key not in operation:
                raise IrValidationError(
                    "missing modifier prop", modifier=name, prop=key
                )
        for key, item in operation.items():
            if key == "type":
                continue
            declared = spec.get(key)
            if declared is None or not validate_prop(item, declared, intents=intents):
                raise IrValidationError(
                    "invalid modifier prop", modifier=name, prop=key
                )


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
