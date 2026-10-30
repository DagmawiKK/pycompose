"""Immutable host action envelopes validated against generated registry tables."""

from __future__ import annotations

import json
from collections.abc import Callable, Container, Mapping
from dataclasses import dataclass
from typing import cast

from pycompose.errors import BridgeError, IrValidationError
from pycompose.host.bridge._generated.payloads import IncrementPayload, SubmitPayload
from pycompose.model.canonical import FrozenJsonValue, freeze_json
from pycompose.model.catalog.lock import REGISTRY
from pycompose.model.catalog.registry import PropDef
from pycompose.ui._rules import validate_prop
from pycompose.ui.intents import IntentSpec, check_payload

__all__ = [
    "MAIN_SURFACE",
    "Action",
    "IncrementPayload",
    "SubmitPayload",
    "decode_action",
]

MAIN_SURFACE = "main"
"""The one surface a session hosts until it hosts several."""


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
        action_id: Registry action id, or an app handler's name.
        payload: Immutable payload fields.
        binding: Active app binding, when the action came from a control.
        app_handler: True when the id names a handler the app registered rather
            than a registry action or a control's binding. Such a payload has no
            wire contract to check here; the handler's own declared fields are
            the contract, and they are checked when it is dispatched.
        seq: The host's sequence number for a settled value it reported, which
            the snapshot echoes so the host can tell a stale answer from a
            current one; None for actions that report nothing.
        trace: The host's trace id for this input, or None.
    """

    action_id: str
    payload: Mapping[str, FrozenJsonValue]
    binding: IntentSpec | None = None
    app_handler: bool = False
    seq: int | None = None
    trace: str | None = None

    @property
    def target(self) -> object:
        """Return what the action was sent to, as its control carried it.

        Returns:
            The intent object for an app handler, or the registry action's name.
        """
        return self.binding.intent() if self.binding is not None else self.action_id

    def __post_init__(self) -> None:
        if self.binding is not None:
            check_payload(self.payload, self.binding.event_fields)
            object.__setattr__(self, "payload", freeze_json(self.payload))
            return
        if self.app_handler:
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


def _envelope(action_json: str) -> dict[str, object]:
    """Parse an action envelope and check its framing fields.

    Args:
        action_json: The host's JSON envelope.

    Returns:
        The envelope's fields.

    Raises:
        BridgeError: If the JSON or a framing field is invalid.
    """
    try:
        if not isinstance(action_json, str):
            raise BridgeError("action JSON must be a string")
        raw: object = json.loads(action_json, object_pairs_hook=_unique_object)
    except (TypeError, ValueError, RecursionError) as exc:
        raise BridgeError("malformed action JSON") from exc
    if not isinstance(raw, dict) or set(raw) - {
        "intent",
        "fields",
        "payload",
        "seq",
        "serial",
        "surface",
        "trace",
    }:
        raise BridgeError("invalid action envelope")
    if raw.get("surface", MAIN_SURFACE) != MAIN_SURFACE:
        raise BridgeError("unknown surface", surface=raw.get("surface"))
    for name in ("seq", "serial"):
        value = raw.get(name)
        if value is not None and (type(value) is not int or value < 1):
            raise BridgeError(f"{name} must be a positive integer")
    if raw.get("trace") is not None and not isinstance(raw["trace"], str):
        raise BridgeError("trace must be a string")
    return raw


Contracts = Callable[[str], Mapping[str, PropDef] | None]
"""The payload contract of an app handler the session registered, by its id."""


def decode_action(
    action_json: str,
    *,
    contracts: Contracts | None = None,
    handlers: Container[str] | None = None,
) -> Action:
    """Decode a host action and fill declared optional defaults.

    A control carries an intent: a handler and the fields it bound. A tap sends
    that intent back with the event's own fields, so its meaning is fixed by
    what the user saw, never by whichever snapshot is current. The handler's
    declared fields are the contract both are checked against. An event with no
    control -- a background result -- names the handler with no bound fields.

    Args:
        action_json: JSON envelope with the intent, its bound fields, the event
            payload, an optional report sequence number, the serial of the
            snapshot it was dispatched against, the surface it names and an
            optional trace id.
        contracts: Looks up an app handler's declared fields; None knows only
            registry actions and lifecycle events.
        handlers: Ids registered without declared fields; their payload is
            checked by the handler when it is dispatched.

    Returns:
        An action ready for handler dispatch.

    Raises:
        BridgeError: If the envelope or its fields are invalid.
    """
    raw = _envelope(action_json)
    seq = cast("int | None", raw.get("seq"))
    trace = cast("str | None", raw.get("trace"))
    action_id = raw.get("intent")
    if not isinstance(action_id, str) or not action_id:
        raise BridgeError("intent must name a handler or a registry action")
    fields, payload = raw.get("fields", {}), raw.get("payload", {})
    if not isinstance(fields, dict) or not isinstance(payload, dict):
        raise BridgeError("fields and payload must be objects", action_id=action_id)
    # A registry action or lifecycle event keeps its own contract, even when an
    # app handler's alias happens to share its name.
    if action_id in REGISTRY.actions or action_id in REGISTRY.lifecycle:
        if fields:
            raise BridgeError("registry actions bind no fields", action_id=action_id)
        return Action(action_id, payload, seq=seq, trace=trace)
    contract = contracts(action_id) if contracts is not None else None
    if contract is None:
        if fields or action_id not in (handlers or ()):
            raise BridgeError("unknown action", action_id=action_id)
        return Action(action_id, payload, app_handler=True, seq=seq, trace=trace)
    try:
        binding = IntentSpec(action_id, contract, fields)
        return Action(action_id, payload, binding, seq=seq, trace=trace)
    except IrValidationError as exc:
        raise BridgeError("invalid app action payload", action_id=action_id) from exc
