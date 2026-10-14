"""Immutable host action envelopes validated against generated registry tables."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from pycompose.bridge.generated_payloads import IncrementPayload, SubmitPayload
from pycompose.core.action_binding import BindingSpec, check_payload
from pycompose.core.registry_types import PropDef
from pycompose.errors import BridgeError, IrValidationError
from pycompose.ir.generated_validators import REGISTRY
from pycompose.ir.validator import validate_prop
from pycompose.utils.json_canonical import FrozenJsonValue, freeze_json

__all__ = ["Action", "IncrementPayload", "SubmitPayload", "decode_action"]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise BridgeError("duplicate action field", prop=key)
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class Action:
    """A validated, detached action and its defaulted payload.

    Attributes:
        action_id: Registry action id.
        payload: Immutable registry-validated payload fields.
        binding: Active app binding, when not using a legacy registry action.
    """

    action_id: str
    payload: Mapping[str, FrozenJsonValue]
    binding: BindingSpec | None = None

    def __post_init__(self) -> None:
        if self.binding is not None:
            check_payload(self.payload, self.binding.event_fields)
            object.__setattr__(self, "payload", freeze_json(self.payload))
            return
        object.__setattr__(
            self, "payload", _prepare_payload(self.action_id, self.payload)
        )


def _contract(action_id: str) -> Mapping[str, PropDef] | None:
    """Return the payload contract for a declared action or lifecycle event.

    Args:
        action_id: Candidate id from the host envelope.

    Returns:
        The registry payload contract, or None when the id is undeclared.
    """
    for table in (REGISTRY.actions, REGISTRY.lifecycle):
        spec = table.get(action_id)
        if spec is not None:
            return spec.payload
    return None


def _prepare_payload(
    action_id: str, supplied: Mapping[str, FrozenJsonValue]
) -> Mapping[str, FrozenJsonValue]:
    spec = _contract(action_id) if isinstance(action_id, str) else None
    if spec is None:
        raise BridgeError("unknown action", action_id=action_id)
    if not isinstance(supplied, Mapping):
        raise BridgeError("payload must be an object", action_id=action_id)
    payload = dict(supplied)
    if set(payload) - spec.keys():
        raise BridgeError("unknown payload fields", action_id=action_id)
    for name, prop in spec.items():
        if name not in payload:
            if prop.required:
                raise BridgeError(
                    "missing payload field", action_id=action_id, prop=name
                )
            if prop.has_default:
                payload[name] = freeze_json(prop.default)
        if name in payload and not validate_prop(payload[name], prop):
            raise BridgeError("invalid payload field", action_id=action_id, prop=name)
    return cast("Mapping[str, FrozenJsonValue]", freeze_json(payload))


def decode_action(
    action_json: str, *, bindings: Mapping[str, BindingSpec] | None = None
) -> Action:
    """Decode a host action and fill declared optional defaults.

    Args:
        action_json: JSON envelope with actionId and optional payload object.
        bindings: App bindings from the active validated snapshot.

    Returns:
        An action ready for handler dispatch.

    Raises:
        BridgeError: If the envelope or registry payload is invalid.
    """
    try:
        if not isinstance(action_json, str):
            raise BridgeError("action JSON must be a string")
        raw: object = json.loads(action_json, object_pairs_hook=_unique_object)
    except (TypeError, ValueError, RecursionError) as exc:
        raise BridgeError("malformed action JSON") from exc
    if not isinstance(raw, dict) or set(raw) - {"actionId", "payload"}:
        raise BridgeError("invalid action envelope")
    action_id = raw.get("actionId")
    if not isinstance(action_id, str) or (
        action_id not in REGISTRY.actions
        and action_id not in REGISTRY.lifecycle
        and action_id not in (bindings or {})
    ):
        raise BridgeError("unknown action", action_id=action_id)
    payload = raw.get("payload", {})
    if not isinstance(payload, dict):
        raise BridgeError("payload must be an object", action_id=action_id)
    binding = (bindings or {}).get(action_id)
    try:
        return Action(action_id, payload, binding)
    except IrValidationError as exc:
        raise BridgeError("invalid app action payload", action_id=action_id) from exc
