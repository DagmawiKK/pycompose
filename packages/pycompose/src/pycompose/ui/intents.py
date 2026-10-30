"""Intents: the data a control sends to its screen's view model.

A subclass is a frozen dataclass (it is an :class:`AppState`), so its fields are
typed and encoded by the same codec as saved state. Passing an instance to a
control binds every field; passing the class lets the event supply them; and
``Intent.bind(**fields)`` binds some now and leaves the rest to the event.

A bound intent is the id a control's prop holds until lowering, carrying its
:class:`IntentSpec`; the snapshot states each handler's payload contract once,
and the checks here read it back.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from dataclasses import MISSING, dataclass, fields
from types import MappingProxyType, UnionType
from typing import (
    Any,
    ClassVar,
    Literal,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from pycompose.errors import IrValidationError, StateError
from pycompose.model.canonical import (
    FrozenJsonValue,
    canonical_json,
    freeze_json,
    thaw_json,
)
from pycompose.model.catalog.registry import PropDef
from pycompose.model.nodes.expressions import Expression
from pycompose.model.nodes.props import JsonValue, to_camel_case
from pycompose.state.app_state import AppState

__all__ = [
    "BoundIntent",
    "Intent",
    "IntentSpec",
    "check_payload",
    "intent_class",
    "lower_action",
    "read_intents",
    "valid_intent",
]

_INTENTS: dict[str, type[Intent]] = {}
_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")


_BOUND_ID = re.compile(r"app\.[A-Za-z0-9_.-]+")


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
class IntentSpec:
    """What a bound intent carries; payload names are camelCase wire names.

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


class BoundIntent(str):
    """The id a control's prop holds, carrying its spec until lowering."""

    __slots__ = ("spec",)
    spec: IntentSpec

    def __new__(cls, bound_id: str, spec: IntentSpec) -> BoundIntent:
        if _BOUND_ID.fullmatch(bound_id) is None:
            raise IrValidationError("invalid bound intent id", bound_id=bound_id)
        instance = super().__new__(cls, bound_id)
        object.__setattr__(instance, "spec", spec)
        return instance

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("bound intents are immutable")


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


class Intent(AppState):
    """Base for what a control asks its screen's view model to do.

    Intents state a target rather than a change -- ``SetExpanded(id, True)``,
    not ``Toggle(id)`` -- so a duplicate, or a tap on a screen that is no longer
    current, still does the right thing.
    """

    _contract: ClassVar[Mapping[str, PropDef] | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._contract = None
        # A reload re-imports a module and defines the class again; the newest wins.
        _INTENTS[intent_name(cls)] = cls

    @classmethod
    def contract(cls) -> Mapping[str, PropDef]:
        """Return this intent's fields as a payload contract, by wire name.

        Returns:
            Each field's type, and whether an event must supply it.
        """
        if cls._contract is None:
            hints = get_type_hints(cls)
            cls._contract = {
                to_camel_case(field.name): payload_field(
                    hints[field.name],
                    field.default is MISSING and field.default_factory is MISSING,
                )
                for field in fields(cast("Any", cls))
            }
        return cls._contract

    @classmethod
    def bind(cls, **values: Any) -> BoundIntent:
        """Bind some fields now and leave the rest for the event to supply.

        Args:
            **values: Fixed field values, by Python name.

        Returns:
            The bound intent a control carries.

        Raises:
            StateError: If a value names no field of this intent.
        """
        known = {field.name for field in fields(cast("Any", cls))}
        if set(values) - known:
            raise StateError(
                "bind names fields the intent does not have",
                intent=intent_name(cls),
                fields=",".join(sorted(set(values) - known)),
            )
        bound = {to_camel_case(key): value for key, value in values.items()}
        name = intent_name(cls)
        key = "app." + _UNSAFE.sub("_", name)
        if bound:
            key += "." + hashlib.sha256(canonical_json(bound).encode()).hexdigest()[:12]
        return BoundIntent(key, IntentSpec(name, cls.contract(), bound))

    def bound(self) -> BoundIntent:
        """Return this intent with every field bound, as a control carries it.

        Returns:
            The bound intent.
        """
        values = {f.name: getattr(self, f.name) for f in fields(cast("Any", self))}
        return type(self).bind(**values)


def payload_field(annotation: object, required: bool) -> PropDef:
    """Return the payload definition an intent field declares.

    Args:
        annotation: The field's type: a scalar, a string ``Literal`` or an
            optional one.
        required: Whether an event must supply it.

    Returns:
        Its definition.

    Raises:
        StateError: If the type is outside the payload vocabulary.
    """
    # ``int | None``: a report that may carry null (a cleared date selection).
    args = get_args(annotation)
    if get_origin(annotation) in {Union, UnionType} and type(None) in args:
        rest = [arg for arg in args if arg is not type(None)]
        if len(rest) == 1:
            inner = payload_field(rest[0], required)
            return PropDef(
                type=inner.type, values=inner.values, required=required, nullable=True
            )
    types: dict[object, str] = {
        str: "string",
        bool: "boolean",
        int: "integer",
        float: "number",
    }
    if get_origin(annotation) is Literal:
        values = get_args(annotation)
        if not values or not all(isinstance(value, str) for value in values):
            raise StateError("intent Literal values must be strings")
        return PropDef(type="enum", values=values, required=required)
    kind = types.get(annotation)
    if kind is None:
        raise StateError("unsupported intent field type", annotation=str(annotation))
    return PropDef(type=kind, required=required)


def intent_name(cls: type) -> str:
    """Return the name an intent class travels under.

    Args:
        cls: An intent class.

    Returns:
        Its module and qualified name.
    """
    return f"{cls.__module__}.{cls.__qualname__}"


def intent_class(name: str) -> type[Intent] | None:
    """Return the intent class a wire name names.

    Args:
        name: The name an intent travelled under.

    Returns:
        The class, or None when no defined intent has that name.
    """
    return _INTENTS.get(name)


def lower_action(value: object) -> JsonValue:
    """Turn an action a control takes into wire data or a bound intent.

    An intent class binds nothing of its own; an intent instance binds every
    field. An expression is wire data from here on.

    Args:
        value: A prop value as the app passed it.

    Returns:
        The value the node holds.
    """
    if isinstance(value, Intent):
        return value.bound()
    if isinstance(value, type) and issubclass(value, Intent):
        return value.bind()
    if isinstance(value, Expression):
        return cast("JsonValue", value.to_wire())
    return cast("JsonValue", value)
