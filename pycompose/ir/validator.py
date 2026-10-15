"""Fail-closed validation driven by generated registry tables.

Valid snapshots retain identity; release reconstruction touches only changed
nodes and ancestors. Registry/present prop ordering preserves diagnostic order,
not wire ordering. Traversal costs O(N + V + identity bytes), plus prop sorting
and materialized diagnostics. Ancestor paths cost O(depth) only on failure.
Dropped branches are still traversed for cycles: structural cycles invalidate
the entire candidate even when component policy would otherwise discard it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import cast

from pycompose.core.action_binding import ActionBinding, read_bindings
from pycompose.core.node import Node, Props
from pycompose.core.registry_types import PropDef
from pycompose.core.resources import valid_resource
from pycompose.core.traversal import NodeCycleError, walk_nodes
from pycompose.core.values import validate_bounds, validate_number, validate_value
from pycompose.errors import ComponentRegistryError, IrValidationError
from pycompose.ir.data import DATA_SCHEMA, read_data
from pycompose.ir.effects import EFFECTS_SCHEMA, read_effects
from pycompose.ir.generated_validators import (
    MIN_LIBRARY_VERSION,
    MIN_SCHEMA_VERSION,
    REGISTRY,
    SCHEMA_VERSION,
)
from pycompose.ir.model import IRRoot
from pycompose.schema.version import require_version
from pycompose.utils.json_canonical import FrozenJsonValue, check_json

__all__ = [
    "ValidationIssue",
    "ValidationResult",
    "validate_component",
    "validate_ir",
    "validate_modifier",
    "validate_prop",
]


_TYPE_CHECKS: dict[str, Callable[[object, PropDef], bool]] = {
    "string": lambda value, _: isinstance(value, str),
    "resource": lambda value, prop: valid_resource(value, prop.values),
    "color": lambda value, _: isinstance(value, str),
    "boolean": lambda value, _: isinstance(value, bool),
    "integer": lambda value, _: isinstance(value, int) and not isinstance(value, bool),
    "durationMs": lambda value, _: isinstance(value, int)
    and not isinstance(value, bool),
    "number": lambda value, _: isinstance(value, int | float)
    and not isinstance(value, bool),
    "dp": lambda value, _: _is_native_float(value),
    "modifier": lambda value, _: isinstance(value, Mapping),
    "enum": lambda value, prop: isinstance(value, str) and value in prop.values,
    "actionId": lambda value, _: isinstance(value, ActionBinding)
    or (isinstance(value, str) and value in REGISTRY.actions),
}


def validate_prop(
    value: object, prop: PropDef, *, action_ids: frozenset[str] = frozenset()
) -> bool:
    """Check a JSON value against a generated prop or payload definition.

    Args:
        value: Candidate value, including frozen JSON containers.
        prop: Definition from the component registry.
        action_ids: Active app binding ids declared in this snapshot.

    Returns:
        Whether the type, bounds and registry references are valid.
    """
    if value is None:
        return prop.nullable
    check = _TYPE_CHECKS.get(prop.type)
    if prop.value_type is not None and isinstance(value, Mapping):
        return _valid_value(value, prop)
    binding = prop.type == "actionId" and isinstance(value, str) and value in action_ids
    if check is None or not (binding or check(value, prop)):
        return False
    try:
        if prop.type == "modifier":
            validate_modifier(value, action_ids=action_ids)
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


def validate_modifier(
    value: object, *, action_ids: frozenset[str] = frozenset()
) -> None:
    """Validate ordered operations using generated modifier definitions.

    Legacy modifier objects without operations remain JSON-compatible. Invalid
    JSON propagates IrValidationError from the shared checker.

    Args:
        value: Ordinary or frozen modifier object.
        action_ids: Active app binding ids declared in this snapshot.

    Raises:
        IrValidationError: If operations, props or action references are invalid.
    """
    check_json(value)
    if not isinstance(value, Mapping):
        raise IrValidationError("modifier must be an object")
    if "operations" not in value:
        return
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
            if declared is None or not validate_prop(
                item, declared, action_ids=action_ids
            ):
                raise IrValidationError(
                    "invalid modifier prop", modifier=name, prop=key
                )


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """A deterministic diagnostic the boundary may log or display.

    Attributes:
        message: Human-readable validation failure.
        node_id: Offending node id.
        node_type: Offending component name.
        path: Node path in the snapshot.
        prop: Offending prop, when applicable.
    """

    message: str
    node_id: str
    node_type: str
    path: tuple[str, ...]
    prop: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Validated IR plus release degradation diagnostics.

    Attributes:
        snapshot: Safe snapshot, or None when no root can be rendered.
        issues: Failures encountered in stable traversal order.
    """

    snapshot: IRRoot | None
    issues: tuple[ValidationIssue, ...] = ()


def _section_ok(
    validation: _Validation,
    metadata: Mapping[str, object] | None,
    read: Callable[[Mapping[str, object] | None], object],
    absent: object,
    invalid: str,
    stale: str,
    since: str | None,
    root: Node,
) -> bool:
    """Check one metadata section is well formed and this schema can carry it.

    Args:
        validation: Collector for any diagnostic raised here.
        metadata: Snapshot metadata, or None when the snapshot carries none.
        read: Section reader from this module.
        absent: The exact object the reader returns when nothing was published.
        invalid: Diagnostic for a malformed section.
        stale: Diagnostic for a section this schema cannot carry.
        since: First schema exposing the section, or None when ungated.
        root: Node attributed in any diagnostic.

    Returns:
        False when the snapshot must not be published at all.
    """
    try:
        value = read(metadata)
    except (IrValidationError, ComponentRegistryError):
        validation.report(invalid, root)
        return False
    if value is not absent and since is not None and not validation.available(since):
        validation.report(stale, root)
        return False
    return True


def validate_ir(snapshot: IRRoot, *, debug: bool = True) -> ValidationResult:
    """Validate a snapshot against the generated component registry.

    Debug failures raise IrValidationError with node/prop context. Version
    incompatibility propagates SchemaError in either mode; never emit a snapshot
    using a contract the runtime cannot validate. Release mode drops invalid
    subtrees and ignores unknown/invalid optional props, returning diagnostics.

    Args:
        snapshot: Candidate full snapshot.
        debug: Raise on invalid IR instead of returning degradation diagnostics.

    Returns:
        The validated snapshot and deterministic diagnostics.

    """
    require_version(
        snapshot.schema_version,
        minimum=MIN_SCHEMA_VERSION,
        maximum=SCHEMA_VERSION,
        supported=REGISTRY.supported_schema_versions or (SCHEMA_VERSION,),
    )
    require_version(snapshot.version, minimum=MIN_LIBRARY_VERSION, field="version")
    validation = _Validation(debug, snapshot.schema_version)
    metadata = snapshot.metadata
    if metadata is not None:
        try:
            check_json(metadata)
        except (IrValidationError, TypeError, ValueError):
            validation.report("invalid metadata", snapshot.root)
            metadata = None
    try:
        bindings = read_bindings(metadata)
    except (IrValidationError, ComponentRegistryError):
        validation.report("invalid app action bindings", snapshot.root)
        return ValidationResult(None, tuple(validation.issues))
    if bindings and not validation.available("1.2.0"):
        validation.report("app actions require newer schema", snapshot.root)
        return ValidationResult(None, tuple(validation.issues))
    # Effects and app data are checked for publishability, not read back here.
    if not _section_ok(
        validation,
        metadata,
        read_effects,
        (),
        "invalid snapshot effects",
        "effects require newer schema",
        EFFECTS_SCHEMA,
        snapshot.root,
    ):
        return ValidationResult(None, tuple(validation.issues))
    if not _section_ok(
        validation,
        metadata,
        read_data,
        None,
        "invalid app data",
        "app data requires newer schema",
        DATA_SCHEMA,
        snapshot.root,
    ):
        return ValidationResult(None, tuple(validation.issues))
    validation.action_ids = frozenset(bindings)
    root = validation.node(snapshot.root)
    safe: IRRoot | None = snapshot
    if root is None:
        safe = None
    elif root is not snapshot.root or metadata is not snapshot.metadata:
        safe = replace(snapshot, root=root, metadata=metadata)
    return ValidationResult(snapshot=safe, issues=tuple(validation.issues))


def validate_component(node: Node) -> None:
    """Check one component's props and immediate child rules, fail-closed.

    Descendants and global identities are checked by validate_ir after emission.
    Constructors use this seam without repeatedly validating whole subtrees.
    Invalid data propagates IrValidationError with node/prop context.

    Args:
        node: Candidate component node.
    """
    validation = _Validation(debug=True)
    frame = validation.prepare(node)
    if frame is not None and len(node.children) < frame.minimum:
        validation.report("too few children", node)


@dataclass(slots=True)
class _NodeFrame:
    props: Props
    minimum: int
    allow_children: bool
    children: list[Node] = field(default_factory=list)


class _Validation:
    def __init__(self, debug: bool, schema_version: str = SCHEMA_VERSION) -> None:
        self.debug = debug
        self.schema_version = schema_version
        self.action_ids: frozenset[str] = frozenset()
        self.issues: list[ValidationIssue] = []
        self.ids: set[str] = set()
        self.path: list[str] = []

    def report(self, message: str, node: Node, prop: str | None = None) -> None:
        path = tuple(self.path) if self.path else (node.id,)
        if self.debug:
            raise IrValidationError(
                message, node_id=node.id, node_type=node.type, path=path, prop=prop
            )
        self.issues.append(ValidationIssue(message, node.id, node.type, path, prop))

    def identity(self, node: Node) -> bool:
        if (
            not isinstance(node.id, str)
            or not node.id
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
        if node.id in self.ids:
            self.report("duplicate node id", node)
            return False
        self.ids.add(node.id)
        return True

    def prepare(self, node: Node) -> _NodeFrame | None:
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
        if node.children and not spec.children.allowed:
            self.report("children are not allowed", node)
        safe_props = node.props
        if removed:
            retained = dict(props)
            for key in removed:
                del retained[key]
            safe_props = Props(retained)
        return _NodeFrame(safe_props, spec.children.min or 0, spec.children.allowed)

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
        if len(frame.children) < frame.minimum:
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
        )

    def node(self, root: Node) -> Node | None:
        frames: list[_NodeFrame | None] = []
        safe: Node | None = None
        try:
            for node, entering in walk_nodes(root):
                if entering:
                    self.path.append(node.id)
                    parent = frames[-1] if frames else None
                    enabled = not frames or (
                        parent is not None and parent.allow_children
                    )
                    frames.append(self.prepare(node) if enabled else None)
                else:
                    safe = self.finish(node, frames.pop())
                    self.path.pop()
                    parent = frames[-1] if frames else None
                    if safe is not None and parent is not None:
                        parent.children.append(safe)
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
        return safe
