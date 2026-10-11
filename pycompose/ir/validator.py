"""Fail-closed validation driven by generated registry tables."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from pycompose.core.node import Node, Props
from pycompose.core.registry_types import PropDef
from pycompose.errors import IrValidationError
from pycompose.ir.generated_validators import (
    MIN_LIBRARY_VERSION,
    MIN_SCHEMA_VERSION,
    REGISTRY,
    SCHEMA_VERSION,
)
from pycompose.ir.model import IRRoot
from pycompose.schema.version import require_version
from pycompose.utils.json_canonical import canonical_json, thaw_json

__all__ = ["ValidationIssue", "ValidationResult", "validate_ir"]


_TYPE_CHECKS: dict[str, Callable[[object, PropDef], bool]] = {
    "string": lambda value, _: isinstance(value, str),
    "color": lambda value, _: isinstance(value, str),
    "boolean": lambda value, _: isinstance(value, bool),
    "integer": lambda value, _: isinstance(value, int) and not isinstance(value, bool),
    "durationMs": lambda value, _: isinstance(value, int)
    and not isinstance(value, bool),
    "number": lambda value, _: isinstance(value, int | float)
    and not isinstance(value, bool),
    "dp": lambda value, _: isinstance(value, int | float)
    and not isinstance(value, bool),
    "modifier": lambda value, _: isinstance(value, dict),
    "enum": lambda value, prop: isinstance(value, str) and value in prop.values,
    "actionId": lambda value, _: isinstance(value, str) and value in REGISTRY.actions,
}


def _valid_prop(value: object, prop: PropDef) -> bool:
    check = _TYPE_CHECKS.get(prop.type)
    if check is None or not check(value, prop):
        return False
    try:
        canonical_json(value)
    except IrValidationError:
        return False
    return True


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
        snapshot.schema_version, minimum=MIN_SCHEMA_VERSION, maximum=SCHEMA_VERSION
    )
    require_version(snapshot.version, minimum=MIN_LIBRARY_VERSION, field="version")
    validation = _Validation(debug)
    metadata = snapshot.metadata
    if metadata is not None:
        try:
            canonical_json(thaw_json(metadata))
        except (IrValidationError, TypeError, ValueError):
            validation.report("invalid metadata", snapshot.root, (snapshot.root.id,))
            metadata = None
    root = validation.node(snapshot.root, (snapshot.root.id,))
    safe = replace(snapshot, root=root, metadata=metadata) if root is not None else None
    return ValidationResult(snapshot=safe, issues=tuple(validation.issues))


class _Validation:
    def __init__(self, debug: bool) -> None:
        self.debug = debug
        self.issues: list[ValidationIssue] = []
        self.ids: set[str] = set()

    def report(
        self, message: str, node: Node, path: tuple[str, ...], prop: str | None = None
    ) -> None:
        if self.debug:
            raise IrValidationError(
                message, node_id=node.id, node_type=node.type, path=path, prop=prop
            )
        self.issues.append(ValidationIssue(message, node.id, node.type, path, prop))

    def identity(self, node: Node, path: tuple[str, ...]) -> bool:
        if (
            not isinstance(node.id, str)
            or not node.id
            or not isinstance(node.type, str)
            or not node.type
        ):
            self.report("invalid node identity", node, path)
            return False
        try:
            canonical_json(node.id)
            canonical_json(node.type)
        except IrValidationError:
            self.report("invalid node identity", node, path)
            return False
        if node.id in self.ids:
            self.report("duplicate node id", node, path)
            return False
        self.ids.add(node.id)
        return True

    def node(self, node: Node, path: tuple[str, ...]) -> Node | None:
        if not self.identity(node, path):
            return None
        spec = REGISTRY.components.get(node.type)
        if spec is None:
            self.report("unknown component", node, path)
            return None
        props = node.props.to_wire()
        invalid_required = False
        for name, declared in sorted(spec.props.items()):
            if declared.required and name not in props:
                self.report("missing required prop", node, path, name)
                invalid_required = True
        for name in sorted(node.props):
            prop = spec.props.get(name)
            if prop is None:
                self.report("unknown prop", node, path, name)
                del props[name]
            elif not _valid_prop(props[name], prop):
                self.report("invalid prop value", node, path, name)
                del props[name]
                invalid_required |= prop.required
        if invalid_required:
            return None
        children: list[Node] = []
        source_children = node.children
        if source_children and not spec.children.allowed:
            self.report("children are not allowed", node, path)
            source_children = ()
        for child in source_children:
            safe = self.node(child, (*path, child.id))
            if safe is not None:
                children.append(safe)
        if len(children) < (spec.children.min or 0):
            self.report("too few children", node, path)
            return None
        return replace(node, props=Props(props), children=tuple(children))
