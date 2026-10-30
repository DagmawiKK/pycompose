"""Intents: the data a control sends to its screen's view model.

A subclass is a frozen dataclass (it is an :class:`AppState`), so its fields are
typed and encoded by the same codec as saved state. Passing an instance to a
control binds every field; passing the class lets the event supply them; and
``Intent.bind(**fields)`` binds some now and leaves the rest to the event.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import MISSING, fields
from types import UnionType
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

from pycompose.contract.registry_types import PropDef
from pycompose.core.action_binding import ActionBinding, BindingSpec
from pycompose.core.expressions import Expression
from pycompose.core.props import JsonValue, to_camel_case
from pycompose.errors import StateError
from pycompose.state.app_state import AppState
from pycompose.utils.json_canonical import canonical_json

__all__ = ["Intent", "intent_class", "lower_action"]

_INTENTS: dict[str, type[Intent]] = {}
_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")


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
    def bind(cls, **values: Any) -> ActionBinding:
        """Bind some fields now and leave the rest for the event to supply.

        Args:
            **values: Fixed field values, by Python name.

        Returns:
            The binding a control carries.

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
        return ActionBinding(key, BindingSpec(name, cls.contract(), bound))

    def to_binding(self) -> ActionBinding:
        """Return this intent with every field bound, as a control carries it.

        Returns:
            The binding.
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
    """Turn an action a control takes into wire data or a binding.

    An intent class binds nothing of its own; an intent instance binds every
    field. An expression is wire data from here on.

    Args:
        value: A prop value as the app passed it.

    Returns:
        The value the node holds.
    """
    if isinstance(value, Intent):
        return value.to_binding()
    if isinstance(value, type) and issubclass(value, Intent):
        return value.bind()
    if isinstance(value, Expression):
        return cast("JsonValue", value.to_wire())
    return cast("JsonValue", value)
