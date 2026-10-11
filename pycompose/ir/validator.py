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

from pycompose.core.node import Node, Props
from pycompose.core.registry_types import PropDef
from pycompose.core.traversal import NodeCycleError, walk_nodes
from pycompose.errors import IrValidationError
from pycompose.ir.generated_validators import (
    MIN_LIBRARY_VERSION,
    MIN_SCHEMA_VERSION,
    REGISTRY,
    SCHEMA_VERSION,
)
from pycompose.ir.model import IRRoot
from pycompose.schema.version import require_version
from pycompose.utils.json_canonical import check_json

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
    "modifier": lambda value, _: isinstance(value, Mapping),
    "enum": lambda value, prop: isinstance(value, str) and value in prop.values,
    "actionId": lambda value, _: isinstance(value, str) and value in REGISTRY.actions,
}


def _valid_prop(value: object, prop: PropDef) -> bool:
    check = _TYPE_CHECKS.get(prop.type)
    if check is None or not check(value, prop):
        return False
    try:
        check_json(value)
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
            check_json(metadata)
        except (IrValidationError, TypeError, ValueError):
            validation.report("invalid metadata", snapshot.root)
            metadata = None
    root = validation.node(snapshot.root)
    safe: IRRoot | None = snapshot
    if root is None:
        safe = None
    elif root is not snapshot.root or metadata is not snapshot.metadata:
        safe = replace(snapshot, root=root, metadata=metadata)
    return ValidationResult(snapshot=safe, issues=tuple(validation.issues))


@dataclass(slots=True)
class _NodeFrame:
    props: Props
    minimum: int
    allow_children: bool
    children: list[Node] = field(default_factory=list)


class _Validation:
    def __init__(self, debug: bool) -> None:
        self.debug = debug
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
        if spec is None:
            self.report("unknown component", node)
            return None
        props = node.props.values
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
            elif not _valid_prop(props[name], prop):
                self.report("invalid prop value", node, name)
                removed.add(name)
                invalid_required |= prop.required
        if invalid_required:
            return None
        if node.children and not spec.children.allowed:
            self.report("children are not allowed", node)
        safe_props = (
            Props({key: value for key, value in props.items() if key not in removed})
            if removed
            else node.props
        )
        return _NodeFrame(safe_props, spec.children.min or 0, spec.children.allowed)

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
        return replace(node, props=frame.props, children=tuple(frame.children))

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
