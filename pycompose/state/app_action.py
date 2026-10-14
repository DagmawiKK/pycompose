"""Annotated app actions: reusable Python functions, not native registry entries."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import (
    Any,
    Generic,
    Literal,
    NotRequired,
    Required,
    TypeVar,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)

from pycompose.core.action_binding import ActionBinding, BindingSpec
from pycompose.core.props import to_camel_case
from pycompose.core.registry_types import PropDef
from pycompose.errors import StateError
from pycompose.state.state import State

S = TypeVar("S", bound=State)
P = TypeVar("P")

CONTAINER = "container"
"""The one parameter an action may ask the session to supply."""


class AppAction(Generic[S, P]):
    """An annotated transition and its data-only binding factory."""

    def __init__(self, function: Callable[..., S]) -> None:
        self.function = function
        self.name = f"{function.__module__}.{function.__name__}"
        hints = get_type_hints(function)
        signature = inspect.signature(function)
        parameters = list(signature.parameters)
        if len(parameters) < 2:
            raise StateError("action must accept State and one TypedDict payload")
        payload = hints.get(parameters[1])
        if payload is None or not is_typeddict(payload):
            raise StateError("action payload must be annotated with a TypedDict")
        self.injected = self._injected(signature, parameters)
        self.aliases: dict[str, str] = {}
        self.fields: dict[str, PropDef] = {}
        for name, annotation in get_type_hints(payload, include_extras=True).items():
            wire_name = to_camel_case(name)
            if wire_name in self.aliases:
                raise StateError("action payload names collide", prop=name)
            self.aliases[wire_name] = name
            required = name in payload.__required_keys__
            declared: object = annotation
            if get_origin(declared) in {NotRequired, Required}:
                required = get_origin(declared) is Required
                declared = get_args(declared)[0]
            self.fields[wire_name] = _field(declared, required)

    def _injected(
        self, signature: inspect.Signature, parameters: list[str]
    ) -> tuple[str, ...]:
        """Return the names this action wants supplied at dispatch.

        Decided once, here, so that dispatch itself reflects on nothing. Names
        are resolved on the app's own container, never by annotation type: a
        resolver would build a graph whose wiring is only discoverable by running
        it, which is the trade this design deliberately declines. ``container``
        asks for the whole graph; any other name asks for one of its parts.

        Args:
            signature: The action's own signature.
            parameters: Its parameter names, in order.

        Returns:
            The names to supply, empty for an action that wants nothing.

        Raises:
            StateError: If an extra parameter is not keyword-only.
        """
        extra = parameters[2:]
        for name in extra:
            if signature.parameters[name].kind is not inspect.Parameter.KEYWORD_ONLY:
                raise StateError(
                    "an injected dependency must be keyword-only so a typo "
                    "cannot pass silently",
                    parameter=name,
                )
        return tuple(extra)

    def __call__(self, state: S, payload: P, **injected: Any) -> S:
        """Run the transition directly, without going through the runtime.

        This is what makes a test a two-liner: the action is called as if it
        were the function it decorates, and nothing about the host is involved.

        Args:
            state: Snapshot before the transition.
            payload: The bound and event fields, merged.
            **injected: Whatever this action declared it wanted.

        Returns:
            The handler's next State.
        """
        return self.function(state, payload, **injected)

    def bind(self, *, id: str, **values: Any) -> ActionBinding:
        """Declare a stable binding, leaving event-supplied fields unbound.

        Args:
            id: Stable instance key, such as task_42.
            **values: Fixed Python-named payload values, validated immediately.

        Returns:
            A string-compatible immutable declaration for native action props.
        """
        bound = {to_camel_case(key): value for key, value in values.items()}
        return ActionBinding(
            f"app.{self.name}.{id}", BindingSpec(self.name, self.fields, bound)
        )


def _field(annotation: object, required: bool) -> PropDef:
    types: dict[object, str] = {
        str: "string",
        bool: "boolean",
        int: "integer",
        float: "number",
    }
    if get_origin(annotation) is Literal:
        values = get_args(annotation)
        if not values or not all(isinstance(value, str) for value in values):
            raise StateError("action Literal values must be strings")
        return PropDef(type="enum", values=values, required=required)
    kind = types.get(annotation)
    if kind is None:
        raise StateError(
            "unsupported action payload annotation", annotation=str(annotation)
        )
    return PropDef(type=kind, required=required)


def action(function: Callable[..., S]) -> AppAction[S, P]:
    """Define a typed Python transition without modifying the native manifest.

    Args:
        function: Pure State/payload transition with a TypedDict payload annotation.

    Returns:
        A definition whose bind method creates data-only native references.
    """
    return AppAction(function)
