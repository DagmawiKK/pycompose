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
from typing import Any, ClassVar, cast, get_type_hints

from pycompose.contract.registry_types import PropDef
from pycompose.core.action_binding import ActionBinding, BindingSpec
from pycompose.core.props import to_camel_case
from pycompose.errors import StateError
from pycompose.state.app_action import payload_field
from pycompose.state.app_state import AppState
from pycompose.utils.json_canonical import canonical_json

__all__ = ["Intent", "intent_class"]

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
