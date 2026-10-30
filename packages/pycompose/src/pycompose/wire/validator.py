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
from dataclasses import dataclass, field

from pycompose.contract.catalog import (
    MIN_LIBRARY_VERSION,
    MIN_SCHEMA_VERSION,
    REGISTRY,
    SCHEMA_VERSION,
)
from pycompose.contract.registry_types import PropDef
from pycompose.contract.version import require_version
from pycompose.core.action_binding import ActionBinding, read_intents, valid_intent
from pycompose.core.node import Node
from pycompose.core.resources import valid_resource
from pycompose.core.reuse import Reuse
from pycompose.core.values import validate_bounds, validate_number, validate_value
from pycompose.errors import ComponentRegistryError, IrValidationError
from pycompose.utils.json_canonical import check_json
from pycompose.wire.data import DATA_SCHEMA, read_data
from pycompose.wire.echoes import ECHOES_SCHEMA, read_echoes
from pycompose.wire.effects import EFFECTS_SCHEMA, read_effects
from pycompose.wire.host import current_host
from pycompose.wire.model import IRRoot
from pycompose.wire.streams import stream_problems
from pycompose.wire.validator_walk import _Validation

__all__ = [
    "ValidationResult",
    "validate_component",
    "validate_ir",
    "validate_modifier",
    "validate_prop",
]


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
    "actionId": lambda value, _: isinstance(value, ActionBinding)
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


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """A snapshot that passed validation, and what validation read from it.

    Attributes:
        snapshot: The snapshot, unchanged.
        intents: The snapshot's intent contracts by handler id, parsed once here.
    """

    snapshot: IRRoot
    intents: Intents = field(default_factory=dict)


def _section_ok(
    validation: _Validation,
    metadata: Mapping[str, object] | None,
    read: Callable[[Mapping[str, object] | None], object],
    absent: object,
    invalid: str,
    stale: str,
    since: str | None,
    root: Node,
) -> None:
    """Check one metadata section is well formed and this schema can carry it.

    Args:
        validation: Raises any diagnostic found here.
        metadata: Snapshot metadata, or None when the snapshot carries none.
        read: Section reader from this module.
        absent: The exact object the reader returns when nothing was published.
        invalid: Diagnostic for a malformed section.
        stale: Diagnostic for a section this schema cannot carry.
        since: First schema exposing the section, or None when ungated.
        root: Node attributed in any diagnostic.
    """
    try:
        value = read(metadata)
    except (IrValidationError, ComponentRegistryError):
        validation.report(invalid, root)
    if value is not absent and since is not None and not validation.available(since):
        validation.report(stale, root)


def validate_ir(snapshot: IRRoot, *, reuse: Reuse | None = None) -> ValidationResult:
    """Validate a snapshot against the generated component registry, fail-closed.

    Python validates in debug and tests; in release the host's typed parse is
    the one check, and an invalid snapshot is refused whole on either side, so
    the last good one stays on screen. The first invalid node, prop or metadata
    section raises IrValidationError with its context; a version this runtime
    cannot validate raises SchemaError.

    Args:
        snapshot: Candidate full snapshot.
        reuse: The session's subtrees that were clean last pass, skipped when
            they recur; None validates every node.

    Returns:
        The snapshot and the intent contracts it states.
    """
    require_version(
        snapshot.schema_version,
        minimum=MIN_SCHEMA_VERSION,
        maximum=SCHEMA_VERSION,
        supported=REGISTRY.supported_schema_versions or (SCHEMA_VERSION,),
    )
    require_version(snapshot.version, minimum=MIN_LIBRARY_VERSION, field="version")
    validation = _Validation(snapshot.schema_version, host=current_host())
    if reuse is not None:
        reuse.validated.start()
        validation.memo = reuse.validated
    metadata = snapshot.metadata
    if metadata is not None:
        try:
            check_json(metadata)
        except (IrValidationError, TypeError, ValueError):
            validation.report("invalid metadata", snapshot.root)
    try:
        intents = read_intents(metadata)
    except (IrValidationError, ComponentRegistryError):
        validation.report("invalid intent contracts", snapshot.root)
    if intents and not validation.available("1.2.0"):
        validation.report("app actions require newer schema", snapshot.root)
    # Effects, app data and echoes are checked for publishability, not read back.
    for read, absent, invalid, stale, since in (
        (
            read_effects,
            (),
            "invalid snapshot effects",
            "effects require newer schema",
            EFFECTS_SCHEMA,
        ),
        (
            read_data,
            None,
            "invalid app data",
            "app data requires newer schema",
            DATA_SCHEMA,
        ),
        (
            read_echoes,
            None,
            "invalid echoes",
            "echoes require newer schema",
            ECHOES_SCHEMA,
        ),
    ):
        _section_ok(
            validation, metadata, read, absent, invalid, stale, since, snapshot.root
        )
    validation.intents = intents
    validation.node(snapshot.root)
    # An expression may read a holder anywhere in the snapshot.
    for node, prop, message in stream_problems(snapshot.root):
        validation.report(message, node, prop)
    return ValidationResult(snapshot=snapshot, intents=intents)


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
