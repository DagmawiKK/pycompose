"""Immutable data describing app action bindings; no handlers live in IR."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

from pycompose.core.registry_types import PropDef
from pycompose.errors import IrValidationError
from pycompose.utils.json_canonical import FrozenJsonValue, freeze_json, thaw_json

if TYPE_CHECKING:
    from pycompose.core.reuse import SubtreeMemo

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

    def to_wire(self) -> dict[str, object]:
        """Describe this binding using only JSON-compatible values.

        Returns:
            A handler identity, payload schema and fixed payload values.
        """
        return {
            "handlerId": self.handler_id,
            "payload": {key: value.to_mapping() for key, value in self.payload.items()},
            "bound": thaw_json(self.bound),
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


def read_bindings(
    metadata: Mapping[str, object] | None,
    memo: SubtreeMemo[BindingSpec] | None = None,
) -> dict[str, BindingSpec]:
    """Parse data-only binding metadata with fail-closed field/type checks.

    Args:
        metadata: Snapshot metadata containing optional actionBindings.
        memo: Specs parsed last pass, reused for a contract that is the same
            frozen object under the same id; None parses every contract.

    Returns:
        Validated binding declarations by stable id.

    Raises:
        IrValidationError: If declarations or fixed payloads are malformed.
    """
    raw = metadata.get("actionBindings", {}) if metadata is not None else {}
    if not isinstance(raw, Mapping):
        raise IrValidationError("actionBindings must be an object")
    result = {}
    for key, frozen in raw.items():
        spec = memo.get(frozen, key) if memo is not None else None
        if spec is None:
            spec = _read_binding(key, frozen)
            if memo is not None:
                memo.put(frozen, spec, key)
        result[key] = spec
    return result


def _read_binding(key: object, frozen: object) -> BindingSpec:
    """Parse one binding declaration.

    Args:
        key: The binding id.
        frozen: Its frozen contract.

    Returns:
        The validated declaration.

    Raises:
        IrValidationError: If the declaration or its fixed payload is malformed.
    """
    # Snapshot metadata is frozen JSON, so arrays arrive as tuples; thaw to read
    # the declaration with the ordinary dict/list vocabulary.
    value = thaw_json(frozen)
    if (
        not isinstance(key, str)
        or _BINDING.fullmatch(key) is None
        or not isinstance(value, Mapping)
    ):
        raise IrValidationError("invalid app binding declaration")
    if set(value) != {"handlerId", "payload", "bound"}:
        raise IrValidationError("invalid app binding fields")
    handler, fields, bound = value["handlerId"], value["payload"], value["bound"]
    if (
        not isinstance(handler, str)
        or not handler
        or not isinstance(fields, Mapping)
        or not isinstance(bound, Mapping)
    ):
        raise IrValidationError("invalid app binding contract")
    rules = {}
    for name, rule in fields.items():
        if (
            not isinstance(name, str)
            or not isinstance(rule, Mapping)
            or set(rule) - {"type", "required", "values"}
        ):
            raise IrValidationError("invalid app payload schema")
        prop = PropDef.from_mapping(rule, where=name)
        if prop.type not in {"string", "integer", "number", "boolean", "enum"}:
            raise IrValidationError("unsupported app payload type")
        rules[name] = prop
    return BindingSpec(handler, rules, cast("Mapping[str, FrozenJsonValue]", bound))
