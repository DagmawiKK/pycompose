"""Annotated app actions: reusable Python functions, not native registry entries."""

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Callable, Mapping
from typing import (
    Any,
    Generic,
    Literal,
    TypeVar,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from pycompose.core.action_binding import ActionBinding, BindingSpec
from pycompose.core.effect import Effect
from pycompose.core.node import Node
from pycompose.core.props import to_camel_case
from pycompose.core.registry_types import PropDef
from pycompose.errors import StateError
from pycompose.state.app_state import AppState
from pycompose.state.state import State
from pycompose.utils.json_canonical import canonical_json

S = TypeVar("S", bound=State)

CONTAINER = "container"
"""The one parameter an action may ask the session to supply."""


class AppAction(Generic[S]):
    """An annotated transition and its data-only binding factory.

    A handler is a plain function: its first parameter is the snapshot or the
    app shell, each further plain parameter is one payload field typed by its
    annotation and optional when it has a default, and each keyword-only
    parameter names a dependency the session supplies. The signature is the
    whole contract; nothing is declared twice.
    """

    def __init__(self, function: Callable[..., S]) -> None:
        self.function = function
        self.name = f"{function.__module__}.{function.__name__}"
        hints = get_type_hints(function, include_extras=True)
        parameters = list(inspect.signature(function).parameters.values())
        if not parameters:
            raise StateError("action must accept the State or its app shell first")
        first = hints.get(parameters[0].name)
        if first is not None and inspect.isclass(first) and issubclass(first, AppState):
            # Session-native: the handler's first parameter is the app shell,
            # decoded from the snapshot, rather than the snapshot itself.
            self.shell: type[AppState] | None = first
        elif parameters[0].name == "session":
            raise StateError(
                "a session-first action must annotate its shell type",
                parameter=parameters[0].name,
            )
        else:
            self.shell = None
        self.view: Callable[[Any], Node] | None = None
        self.injected = tuple(
            parameter.name
            for parameter in parameters[1:]
            if parameter.kind is inspect.Parameter.KEYWORD_ONLY
        )
        self.aliases: dict[str, str] = {}
        self.fields: dict[str, PropDef] = {}
        for parameter in parameters[1:]:
            if parameter.kind is inspect.Parameter.KEYWORD_ONLY:
                continue
            if parameter.kind is not inspect.Parameter.POSITIONAL_OR_KEYWORD:
                raise StateError(
                    "action fields are plain named parameters", parameter=parameter.name
                )
            declared = hints.get(parameter.name)
            if declared is None:
                raise StateError("action field needs a type", parameter=parameter.name)
            wire_name = to_camel_case(parameter.name)
            if wire_name in self.aliases:
                raise StateError("action field names collide", prop=parameter.name)
            self.aliases[wire_name] = parameter.name
            required = parameter.default is inspect.Parameter.empty
            self.fields[wire_name] = _field(declared, required)

    def __call__(self, state: State, *args: Any, **kwargs: Any) -> State:
        """Run the transition directly, as the function it decorates.

        This is what makes a test a two-liner: the action is called as if it
        were the function, with its fields and dependencies as arguments, and
        nothing about the host is involved. A session-native action runs the
        same way: its shell comes off the snapshot, and the shell it returns
        becomes the next one, version on.

        Args:
            state: Snapshot before the transition.
            *args: Field values, in the handler's order.
            **kwargs: Field values and dependencies, by name.

        Returns:
            The handler's next State.
        """
        return self._transition(
            state, lambda target: self.function(target, *args, **kwargs)
        )

    def run(self, state: State, payload: Mapping[str, Any], **injected: Any) -> State:
        """Run the transition for one dispatched payload.

        Args:
            state: Snapshot before the transition.
            payload: The bound and event fields, merged, by Python name.
            **injected: Whatever this action declared it wanted.

        Returns:
            The handler's next State.
        """
        return self._transition(
            state, lambda target: self.function(target, **payload, **injected)
        )

    def _transition(self, state: State, call: Callable[[Any], Any]) -> State:
        """Run ``call`` on the snapshot, or on its shell for a session action.

        Args:
            state: Snapshot before the transition.
            call: Invokes the handler on its first argument.

        Returns:
            The handler's next State.

        Raises:
            StateError: If a session-native action's snapshot carries no
                matching shell, its return is neither that shell nor a
                respond, or no view was installed to rebuild its screen.
        """
        if self.shell is None:
            return cast("State", call(state))
        shell_type = self.shell
        shell = state.app
        if not isinstance(shell, shell_type):
            raise StateError(
                "a session action runs on a snapshot carrying its shell",
                action_id=self.name,
                app=None if shell is None else type(shell).__name__,
            )
        result: Any = call(shell)
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

    def with_args(self, **values: Any) -> ActionBinding:
        """Bind some fields now, leaving the rest for the event to supply.

        The binding's id derives from the handler and the bound values, so two
        controls bound alike share one binding and two bound differently never
        collide, with nothing for the app to name.

        Args:
            **values: Fixed field values by Python name, validated immediately.

        Returns:
            A string-compatible immutable declaration for native action props.

        Raises:
            StateError: If a value names no field of this action.
        """
        unknown = set(values) - set(self.aliases.values())
        if unknown:
            raise StateError(
                "with_args names fields the action does not take",
                action_id=self.name,
                fields=",".join(sorted(unknown)),
            )
        bound = {to_camel_case(key): value for key, value in values.items()}
        key = f"app.{self.name}"
        if bound:
            digest = hashlib.sha256(canonical_json(bound).encode()).hexdigest()
            key = f"{key}.{digest[:12]}"
        return ActionBinding(key, BindingSpec(self.name, self.fields, bound))

    def binding(self) -> ActionBinding:
        """Return this action bound to nothing, as a control passed it directly.

        Returns:
            The binding every event field of which the event supplies.
        """
        return self.with_args()


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
            "unsupported action field type; a dependency the session supplies "
            "must be keyword-only",
            annotation=str(annotation),
        )
    return PropDef(type=kind, required=required)


def action(function: Callable[..., S]) -> AppAction[S]:
    """Define a typed Python transition without modifying the native manifest.

    Args:
        function: Pure transition whose signature declares its payload fields.

    Returns:
        A definition a control takes directly or through ``with_args``.
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
