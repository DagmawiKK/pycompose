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
    cast,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)

from pycompose.core.action_binding import ActionBinding, BindingSpec
from pycompose.core.effect import Effect
from pycompose.core.node import Node
from pycompose.core.props import to_camel_case
from pycompose.core.registry_types import PropDef
from pycompose.errors import StateError
from pycompose.state.app_state import AppState
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
        first = hints.get(parameters[0])
        if first is not None and inspect.isclass(first) and issubclass(first, AppState):
            # Session-native: the handler's first parameter is the app shell,
            # decoded from the snapshot, rather than the snapshot itself.
            self.shell: type[AppState] | None = first
        elif parameters[0] == "session":
            raise StateError(
                "a session-first action must annotate its shell type",
                parameter=parameters[0],
            )
        else:
            self.shell = None
        self.view: Callable[[Any], Node] | None = None
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

    def __call__(self, state: State, payload: P, **injected: Any) -> State:
        """Run the transition directly, without going through the runtime.

        This is what makes a test a two-liner: the action is called as if it
        were the function it decorates, and nothing about the host is involved.
        A session-native action runs the same way: its shell comes off the
        snapshot, and the shell it returns becomes the next one, version on.

        Args:
            state: Snapshot before the transition.
            payload: The bound and event fields, merged.
            **injected: Whatever this action declared it wanted.

        Returns:
            The handler's next State.

        Raises:
            StateError: If a session-native action's snapshot carries no
                matching shell, its return is neither that shell nor a
                respond, or no view was installed to rebuild its screen.
        """
        if self.shell is None:
            return self.function(state, payload, **injected)
        shell_type = self.shell
        shell = state.app
        if not isinstance(shell, shell_type):
            raise StateError(
                "a session action runs on a snapshot carrying its shell",
                action_id=self.name,
                app=None if shell is None else type(shell).__name__,
            )
        result: Any = self.function(cast("Any", shell), payload, **injected)
        effects: tuple[Effect, ...]
        if isinstance(result, ShellResponse):
            if not isinstance(result.shell, shell_type):
                raise StateError(
                    "respond() must carry the shell the action declared",
                    action_id=self.name,
                )
            shell, effects = result.shell, result.effects
        elif isinstance(result, shell_type):
            shell, effects = result, ()
        else:
            raise StateError(
                "a session action returns its shell, or respond(shell, *effects)",
                action_id=self.name,
            )
        if self.view is None:
            raise StateError(
                "a session action needs the app's view, installed once at startup",
                action_id=self.name,
            )
        return State(
            root=self.view(shell),
            version=state.version + 1,
            app=shell,
            effects=effects,
            slices=state.slices,
            schema_version=state.schema_version,
            min_library_version=state.min_library_version,
        )

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


class ShellResponse:
    """A shell plus the one-shot effects its transition requests."""

    __slots__ = ("effects", "shell")

    def __init__(self, shell: AppState, effects: tuple[Effect, ...]) -> None:
        """Carry a transition's result.

        Args:
            shell: The shell after the transition.
            effects: One-shot host requests, run once in order.
        """
        self.shell = shell
        self.effects = effects


def respond(shell: AppState, *effects: Effect) -> ShellResponse:
    """Return a shell together with the one-shot effects it requests.

    This is how a session-native action asks the host for something -- a
    navigation, a toast, a haptic tick. Returning the shell alone requests
    no effects at all.

    Args:
        shell: The shell after the transition.
        *effects: One-shot host requests, run once in order with this snapshot.

    Returns:
        A response the action may return in place of its shell.
    """
    return ShellResponse(shell, tuple(effects))
