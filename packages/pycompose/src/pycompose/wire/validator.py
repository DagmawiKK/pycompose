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
from pycompose.contract.version import require_version
from pycompose.core.node import Node
from pycompose.core.reuse import Reuse
from pycompose.errors import ComponentRegistryError, IrValidationError
from pycompose.ui._rules import Intents, _Validation
from pycompose.ui.intents import read_intents
from pycompose.utils.json_canonical import check_json
from pycompose.wire.data import DATA_SCHEMA, read_data
from pycompose.wire.echoes import ECHOES_SCHEMA, read_echoes
from pycompose.wire.effects import EFFECTS_SCHEMA, read_effects
from pycompose.wire.host import current_host
from pycompose.wire.model import IRRoot
from pycompose.wire.streams import stream_problems
from pycompose.wire.validator_walk import walk

__all__ = ["ValidationResult", "validate_ir"]


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
    walk(validation, snapshot.root)
    # An expression may read a holder anywhere in the snapshot.
    for node, prop, message in stream_problems(snapshot.root):
        validation.report(message, node, prop)
    return ValidationResult(snapshot=snapshot, intents=intents)
