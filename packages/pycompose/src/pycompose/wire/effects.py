"""Validate declared effect requests and read them back out of metadata."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from pycompose.errors import IrValidationError
from pycompose.model.canonical import FrozenJsonValue
from pycompose.model.catalog.lock import REGISTRY
from pycompose.model.catalog.registry_types import PropDef
from pycompose.model.nodes.effect import Effect
from pycompose.model.nodes.props import JsonValue
from pycompose.ui.intents import check_payload

__all__ = ["EFFECTS_SCHEMA", "lower_effects", "read_effects"]

# Effects arrived in this schema; earlier contracts cannot carry them.
EFFECTS_SCHEMA = "1.4.0"


def _rules(kind: str) -> Mapping[str, PropDef]:
    """Return the declared payload contract for one effect kind.

    Args:
        kind: Candidate effect kind.

    Returns:
        The registry payload contract, empty when the kind takes no payload.

    Raises:
        IrValidationError: If the kind is not declared in the registry.
    """
    spec = REGISTRY.effects.get(kind)
    if spec is None:
        raise IrValidationError("undeclared effect kind", kind=kind)
    return spec.payload


def _check(effect: Effect) -> None:
    """Validate one request against its registry contract, fail-closed.

    Args:
        effect: Candidate request.
    """
    check_payload(dict(effect.payload), _rules(effect.kind))


def lower_effects(
    effects: tuple[Effect, ...],
) -> Mapping[str, JsonValue] | None:
    """Validate requests and build their wire metadata member.

    Args:
        effects: Requests the app attached to this snapshot, in order.

    Returns:
        Metadata to merge into the snapshot, or None when nothing was declared.

    Raises:
        IrValidationError: If any kind or payload breaks the registry contract.
    """
    if not effects:
        return None
    for effect in effects:
        if not isinstance(effect, Effect):
            raise IrValidationError("snapshot effects must be Effect instances")
        _check(effect)
    return cast(
        "Mapping[str, JsonValue]",
        {"effects": [effect.to_wire() for effect in effects]},
    )


def read_effects(metadata: Mapping[str, object] | None) -> tuple[Effect, ...]:
    """Parse effect requests out of snapshot metadata, preserving order.

    Args:
        metadata: Snapshot metadata carrying an optional ``effects`` array.

    Returns:
        Validated effects in declaration order; empty when none were emitted.

    Raises:
        IrValidationError: If the array or any request is malformed.
    """
    raw = metadata.get("effects") if metadata is not None else None
    if raw is None:
        return ()
    if isinstance(raw, str | bytes) or not isinstance(raw, tuple | list):
        raise IrValidationError("effects must be an array")
    result: list[Effect] = []
    for item in raw:
        if not isinstance(item, Mapping) or set(item) != {"kind", "payload"}:
            raise IrValidationError("invalid effect declaration")
        kind = item["kind"]
        if not isinstance(kind, str):
            raise IrValidationError("invalid effect kind")
        payload = item["payload"]
        if not isinstance(payload, Mapping):
            raise IrValidationError("invalid effect payload")
        effect = Effect(kind, cast("Mapping[str, FrozenJsonValue]", payload))
        _check(effect)
        result.append(effect)
    return tuple(result)
