"""Action registry."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import ModuleType
from typing import Any, cast

from pycompose.core.action_binding import BindingSpec, check_payload
from pycompose.core.node import Node
from pycompose.core.props import to_camel_case
from pycompose.errors import StateError
from pycompose.state.app_action import CONTAINER, AppAction
from pycompose.state.state import State

__all__ = ["ActionHandler", "Actions", "Registry", "actions_for_module"]

ActionHandler = Callable[[State, Any], State]


class Actions:
    def __init__(self, *definitions: AppAction[Any, Any]) -> None:
        self._handlers: dict[str, ActionHandler] = {}
        self._definitions = {definition.name: definition for definition in definitions}
        self._container: object | None = None
        self._view: Callable[[Any], Node] | None = None
        self._contracts: dict[str, AppAction[Any, Any]] = {}
        if len(self._definitions) != len(definitions):
            raise StateError("duplicate app action definitions")
        for definition in definitions:
            self._adopt(definition)

    def _adopt(self, definition: AppAction[Any, Any]) -> None:
        """Register one definition under its qualified id and its bare alias.

        Dispatch routes through the definition rather than the bare function it
        wraps, which is what lets a session-native action decode its shell and
        rebuild its screen on every path -- the runtime's and a direct test's
        alike -- without either of them knowing the difference.

        Args:
            definition: The action to register.
        """
        definition.view = self._view
        self.register(definition.name, cast("ActionHandler", definition))
        self._contracts[definition.name] = definition
        self._alias(definition)

    @property
    def injected(self) -> tuple[str, ...]:
        """Return the parameters this registry's actions expect to be supplied.

        Checked once when the session starts rather than when a control is
        tapped, so an app whose actions want a container and which declares no
        container fails to boot instead of failing on the first tap.

        Returns:
            The distinct injected names, in first-seen order.
        """
        names: list[str] = []
        for definition in self._definitions.values():
            for name in definition.injected:
                if name not in names:
                    names.append(name)
        return tuple(names)

    def install_container(self, container: object | None) -> None:
        """Hand this registry the session's container.

        The app builds its registry at import time, before a session exists, so
        the container can only arrive afterwards.

        Args:
            container: The session container, or None when the app declared none.
        """
        self._container = container

    def install_view(self, view: Callable[[Any], Node]) -> None:
        """Hand this registry the app's view, for session-native actions.

        The app declares its view on the entry object, before any snapshot
        exists, so the view can only arrive afterwards -- the same as the
        container.

        Args:
            view: The app's shell renderer, called to rebuild the screen a
                session-native action moved.
        """
        self._view = view
        for definition in self._definitions.values():
            definition.view = view

    def _alias(self, definition: AppAction[Any, Any]) -> None:
        """Also register an action under its bare camelCase name.

        The qualified id (``main.add_task``) is the stable identity; the alias is
        what a host-initiated event such as a lifecycle callback can address
        without knowing the app's module name. First registration wins, so an
        ambiguous alias never silently replaces an existing handler.

        Args:
            definition: Action to expose under its short name.
        """
        _, _, bare = definition.name.rpartition(".")
        alias = to_camel_case(bare)
        if alias and alias not in self._handlers:
            self.register(alias, cast("ActionHandler", definition))
            self._contracts.setdefault(alias, definition)

    def validate_bindings(self, bindings: Mapping[str, BindingSpec]) -> None:
        """Check snapshot bindings against the app's actual annotated handlers.

        Args:
            bindings: Data-only binding declarations emitted by the app.

        Raises:
            StateError: If handlers or annotation-derived contracts do not match.
        """
        for spec in bindings.values():
            definition = self._definitions.get(spec.handler_id)
            if definition is None or definition.fields != dict(spec.payload):
                raise StateError(
                    "unregistered or mismatched app action", action_id=spec.handler_id
                )

    def dispatch_binding(
        self, spec: BindingSpec, state: State, payload: Mapping[str, object]
    ) -> State:
        """Merge immutable fixed values with a validated UI event and run its handler.

        Args:
            spec: Active snapshot binding, never a handler supplied by native code.
            state: Python-owned State before this transition.
            payload: Event fields which cannot override bound values.

        Returns:
            The handler's next frozen State.
        """
        check_payload(payload, spec.event_fields)
        complete = {**spec.bound, **payload}
        check_payload(complete, spec.payload)
        definition = self._definitions[spec.handler_id]
        python_values = {
            definition.aliases[key]: value for key, value in complete.items()
        }
        return self.dispatch(spec.handler_id, state, python_values)

    def register(self, action_id: str, handler: ActionHandler) -> None:
        if not isinstance(action_id, str) or not action_id:
            raise StateError("action_id must be a non-empty string")
        if not callable(handler):
            raise StateError("handler must be callable")
        self._handlers[action_id] = handler

    def dispatch(self, action_id: str, state: State, payload: Any = None) -> State:
        if not isinstance(action_id, str) or not action_id:
            raise StateError("action_id must be a non-empty string")
        if not isinstance(state, State):
            raise StateError("state must be a State instance")
        handler = self._handlers.get(action_id)
        if handler is None:
            raise StateError("unknown action", action_id=action_id)
        named = self._python_payload(action_id, payload)
        self._check_declared(action_id, named)
        result = handler(state, named, **self._supply(action_id))
        if not isinstance(result, State):
            raise StateError("handler must return a State")
        return result

    def _supply(self, action_id: str) -> dict[str, Any]:
        """Return the dependencies this handler declared that it wants.

        ``container`` is the graph itself. Any other name is looked up on it, so
        an action may ask for what it actually uses -- a use case, say -- rather
        than for the object that happens to carry it. Resolution is by name on
        the app's own container, never by annotation, so the wiring is still
        only discoverable by reading it.

        Args:
            action_id: Id the handler is registered under.

        Returns:
            Keyword arguments to pass, empty when it wants nothing.

        Raises:
            StateError: If the handler wants something and the session installed
                no container, or the container does not carry that name. The
                session checks both at startup, so reaching here means dispatch
                happened outside one.
        """
        definition = self._contracts.get(action_id)
        if definition is None or not definition.injected:
            return {}
        if self._container is None:
            raise StateError(
                "this action asks for the container but the app declared none",
                action_id=action_id,
            )
        supplied = {}
        for name in definition.injected:
            if name == CONTAINER:
                supplied[name] = self._container
                continue
            if not hasattr(self._container, name):
                raise StateError(
                    "the app container carries no such dependency",
                    action_id=action_id,
                    dependency=name,
                )
            supplied[name] = getattr(self._container, name)
        return supplied

    def _check_declared(self, action_id: str, payload: Any) -> None:
        """Check a payload against the fields its handler declared.

        A bound action is already checked twice over, by the binding and by
        ``dispatch_binding``. An event with no control -- a background result,
        say -- arrives here straight from the host, and this is the only place
        its shape is enforced.

        Args:
            action_id: Id the payload arrived under.
            payload: The translated payload.
        """
        definition = self._definitions.get(action_id)
        if definition is None or not isinstance(payload, Mapping):
            return
        # The payload has already been translated to the handler's own names, and
        # the declared fields are wire-named, so compare like with like.
        declared = {
            definition.aliases[name]: prop for name, prop in definition.fields.items()
        }
        check_payload(payload, declared, partial=True)

    def _python_payload(self, action_id: str, payload: Any) -> Any:
        """Translate wire-named payload fields to the handler's own names.

        Bound actions already arrive snake-cased by ``dispatch_binding``; a
        host-initiated event such as ``onConfigChanged`` is registry-validated
        and still camelCase, so it is translated here. App code never sees the
        wire spelling.

        Args:
            action_id: Id the payload arrived under.
            payload: Raw payload as received.

        Returns:
            The payload with field names the handler declared.
        """
        definition = self._contracts.get(action_id)
        if definition is None or not isinstance(payload, Mapping):
            return payload
        return {
            definition.aliases.get(name, name): value for name, value in payload.items()
        }

    def __contains__(self, action_id: object) -> bool:
        """Report whether an action id names a handler this app registered.

        Used when decoding an inbound event that no control is bound to -- a
        background result, say. It narrows what the host may name to exactly what
        the app declared, and never widens it.

        Args:
            action_id: The id to look for.

        Returns:
            True when a registered handler, or its alias, carries that id.
        """
        if not isinstance(action_id, str):
            return False
        return action_id in self._handlers or action_id in self._contracts

    def handlers(self) -> Mapping[str, ActionHandler]:
        return self._handlers.copy()


class Registry(Actions):
    """An action registry that collects its own actions and names them.

    ``Actions`` takes the actions it holds as arguments, which means an app
    lists them once to build the registry and again to build whatever a screen
    binds to -- and the two lists are only ever kept in step by discipline.
    That is the wrong trade: forgetting one does not raise, it just produces a
    control nobody can reach.

    A ``Registry`` is used as a decorator instead, so the definition *is* the
    registration:

        actions = Registry()

        @actions
        def new_note(state: State, payload: Nothing) -> State:
            ...

    The same object is what the session finds, and what a screen binds through
    (``actions.new_note.bind(id="new")``), so an action cannot be registered in
    one place and forgotten in the other.
    """

    def __init__(self, *seed: AppAction[Any, Any]) -> None:
        """Open an empty registry.

        Args:
            *seed: Actions to seed it with, if any.
        """
        self._by_name: dict[str, AppAction[Any, Any]] = {}
        super().__init__(*seed)
        for definition in self._definitions.values():
            self._by_name[definition.name.rpartition(".")[2]] = definition

    def __call__(self, function: Callable[..., Any]) -> AppAction[Any, Any]:
        """Define an action and register it.

        Args:
            function: A transition, in the shape ``@action`` accepts: a
                State/payload function, or a session/payload one.

        Returns:
            The definition, so it can be bound and called directly.
        """
        definition: AppAction[Any, Any] = AppAction(function)
        self.add(definition)
        return definition

    def add(self, definition: AppAction[Any, Any]) -> None:
        """Add one action to this registry.

        Args:
            definition: The action to register.

        Raises:
            StateError: If an action of the same name is already registered.
        """
        if definition.name in self._definitions:
            raise StateError(
                "duplicate app action definition", action_id=definition.name
            )
        bare = definition.name.rpartition(".")[2]
        if bare in RESERVED:
            # `__getattr__` runs only when ordinary lookup fails, so an action
            # named `add` would leave `registry.add` resolving to the method and
            # a screen binding through it failing far from the cause.
            raise StateError(
                "action name is reserved by the registry",
                action=definition.name,
                reserved=sorted(RESERVED),
            )
        self._definitions[definition.name] = definition
        self._by_name[bare] = definition
        self._adopt(definition)

    def names(self) -> tuple[str, ...]:
        """Return the bare names of the actions this registry holds.

        Returns:
            The function names, in registration order.
        """
        return tuple(self._by_name)

    def __getattr__(self, name: str) -> AppAction[Any, Any]:
        """Return one of this registry's actions by name.

        Args:
            name: The bare function name, as declared.

        Returns:
            The action definition.

        Raises:
            AttributeError: If no action of that name was registered.
        """
        found: AppAction[Any, Any] | None = self.__dict__.get("_by_name", {}).get(name)
        if found is not None:
            return found
        raise AttributeError(
            f"no action named {name!r}; this registry holds "
            f"{', '.join(self.names()) or 'nothing yet'}"
        )


RESERVED = frozenset(name for name in dir(Registry) if not name.startswith("_"))
"""Names a registry already uses. An action may not take one."""


def actions_for_module(
    module: ModuleType, view: Callable[[Any], Node] | None = None
) -> tuple[Actions, str | None]:
    """Return the action registry an app module declares, ready to render.

    Discovery is shared by every seam that boots an app: the device runtime
    and the preview both need the same registry, or a screen that reaches
    ``actions`` from the context works on one and fails on the other. The
    view installs here too, so a session-native action that cannot decode
    is refused at boot rather than on whichever control a user taps first.

    Args:
        module: The freshly imported app module.
        view: The app's shell renderer, when the entry declares one;
            installed on the registry for session-native actions.

    Returns:
        The module's ``actions`` registry, or one auto-collected from its
        module-level ``AppAction`` definitions, paired with a failure
        message when the registry or the entry is unusable. An empty
        registry is the quietest possible failure -- the app starts,
        renders, and every control is inert because no binding resolves to
        a handler -- so a registry that was declared and came out empty is
        reported rather than rendered blank.
    """
    definitions = [
        value for value in vars(module).values() if isinstance(value, AppAction)
    ]
    actions = getattr(module, "actions", None)
    if actions is None:
        actions = Actions(*definitions)
    elif not isinstance(actions, Actions):
        return Actions(), "app actions must be an Actions instance"
    elif not actions.handlers():
        return (
            Actions(),
            "app declared an actions registry but it holds nothing; check that "
            "it is exported under the module-level name 'actions' and that the "
            "actions are registered on it",
        )
    if view is not None:
        actions.install_view(view)
    elif any(
        getattr(definition, "shell", None) is not None
        for definition in actions.handlers().values()
    ):
        return (
            Actions(),
            "a session-native action needs the app's shell view; this entry "
            "renders data mode",
        )
    return actions, None
