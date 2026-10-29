"""Immutable data describing app action bindings; no handlers live in IR."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from pycompose.contract.registry_types import PropDef
from pycompose.errors import IrValidationError
from pycompose.utils.json_canonical import FrozenJsonValue, freeze_json, thaw_json

BINDING_PATTERN = r"app\.[A-Za-z0-9_.-]+"
_BINDING = re.compile(BINDING_PATTERN)


def check_payload(
    values: Mapping[str, object], rules: Mapping[str, PropDef], *, partial: bool = False
) -> None:
    """Validate the deliberately small app-payload vocabulary.

    Args:
        values: Supplied payload fields, using wire names.
        rules: Annotation-derived field definitions.
        partial: Allow required fields to be filled by a later UI event.

    Raises:
        IrValidationError: If fields, primitive types, or enum values are invalid.
    """
    if set(values) - rules.keys():
        raise IrValidationError("unknown app payload fields")
    for name, rule in rules.items():
        if name not in values:
            if rule.required and not partial:
                raise IrValidationError("missing app payload field", prop=name)
            continue
        value = values[name]
        if value is None and rule.nullable:
            continue
        predicates = {
            "string": isinstance(value, str),
            "boolean": isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, int | float) and not isinstance(value, bool),
            "enum": isinstance(value, str) and value in rule.values,
        }
        if not predicates.get(rule.type, False) or (
            isinstance(value, float) and not math.isfinite(value)
        ):
            raise IrValidationError("invalid app payload field", prop=name)


@dataclass(frozen=True, slots=True)
class BindingSpec:
    """Pure binding data; payload names are canonical camelCase wire names.

    Attributes:
        handler_id: Python handler identity, interpreted only by the Python worker.
        payload: Complete annotation-derived payload contract.
        bound: Fixed values that native events cannot override.
    """

    handler_id: str
    payload: Mapping[str, PropDef]
    bound: Mapping[str, FrozenJsonValue]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        check_payload(self.bound, self.payload, partial=True)
        object.__setattr__(self, "bound", freeze_json(self.bound))

    @property
    def event_fields(self) -> Mapping[str, PropDef]:
        """Return fields supplied by native events, excluding fixed values.

        Returns:
            Event field definitions.
        """
        return {
            key: rule for key, rule in self.payload.items() if key not in self.bound
        }

    def intent(self) -> dict[str, object]:
        """Return the intent a control carries: its handler and its bound fields.

        A tap sends this object back unchanged, so what it means never depends
        on which snapshot is current when it arrives.

        Returns:
            ``{"fields": ..., "intent": ...}`` in canonical key order.
        """
        return {"fields": thaw_json(self.bound), "intent": self.handler_id}

    def contract(self) -> dict[str, object]:
        """Return the handler's payload contract, stated once per handler.

        Returns:
            ``{"payload": ...}``: every field the handler declares.
        """
        return {
            "payload": {key: value.to_mapping() for key, value in self.payload.items()}
        }


class ActionBinding(str):
    """String-compatible declaration carrying immutable data until IR lowering."""

    __slots__ = ("spec",)
    spec: BindingSpec

    def __new__(cls, binding_id: str, spec: BindingSpec) -> ActionBinding:
        if _BINDING.fullmatch(binding_id) is None:
            raise IrValidationError("invalid app binding id", binding_id=binding_id)
        instance = super().__new__(cls, binding_id)
        object.__setattr__(instance, "spec", spec)
        return instance

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("action bindings are immutable")


def read_intents(
    metadata: Mapping[str, object] | None,
) -> dict[str, Mapping[str, PropDef]]:
    """Parse the snapshot's intent contracts with fail-closed field/type checks.

    Args:
        metadata: Snapshot metadata containing an optional ``intents`` section.

    Returns:
        Each handler's payload contract, by handler id.

    Raises:
        IrValidationError: If a contract is malformed.
    """
    raw = metadata.get("intents", {}) if metadata is not None else {}
    if not isinstance(raw, Mapping):
        raise IrValidationError("intents must be an object")
    return {key: _read_contract(key, value) for key, value in raw.items()}


def _read_contract(key: object, frozen: object) -> Mapping[str, PropDef]:
    """Parse one handler's payload contract.

    Args:
        key: The handler id.
        frozen: Its frozen contract.

    Returns:
        Its field definitions.

    Raises:
        IrValidationError: If the contract is malformed.
    """
    # Snapshot metadata is frozen JSON, so arrays arrive as tuples; thaw to read
    # the declaration with the ordinary dict/list vocabulary.
    value = thaw_json(frozen)
    if not isinstance(key, str) or not key or not isinstance(value, Mapping):
        raise IrValidationError("invalid intent contract")
    if set(value) != {"payload"} or not isinstance(value["payload"], Mapping):
        raise IrValidationError("invalid intent contract fields")
    rules = {}
    for name, rule in value["payload"].items():
        if (
            not isinstance(name, str)
            or not isinstance(rule, Mapping)
            or set(rule) - {"type", "required", "values", "nullable"}
        ):
            raise IrValidationError("invalid app payload schema")
        prop = PropDef.from_mapping(rule, where=name)
        if prop.type not in {"string", "integer", "number", "boolean", "enum"}:
            raise IrValidationError("unsupported app payload type")
        rules[name] = prop
    return MappingProxyType(rules)


def valid_intent(value: object, intents: Mapping[str, Mapping[str, PropDef]]) -> bool:
    """Report whether a wire intent names a stated handler with valid bound fields.

    Args:
        value: A candidate ``{"fields": ..., "intent": ...}`` object.
        intents: The snapshot's contracts by handler id.

    Returns:
        True when the handler is stated and its fields fit its contract.
    """
    if not isinstance(value, Mapping) or set(value) != {"fields", "intent"}:
        return False
    handler, fields = value["intent"], value["fields"]
    if not isinstance(handler, str) or handler not in intents:
        return False
    if not isinstance(fields, Mapping):
        return False
    try:
        check_payload(fields, intents[handler], partial=True)
    except IrValidationError:
        return False
    return True
