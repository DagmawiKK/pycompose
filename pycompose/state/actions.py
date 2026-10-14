"""Action registry."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, cast

from pycompose.core.action_binding import BindingSpec, check_payload
from pycompose.core.props import to_camel_case
from pycompose.errors import StateError
from pycompose.state.app_action import AppAction
from pycompose.state.state import State

__all__ = ["ActionHandler", "Actions"]

ActionHandler = Callable[[State, Any], State]


class Actions:
    def __init__(self, *definitions: AppAction[Any, Any]) -> None:
        self._handlers: dict[str, ActionHandler] = {}
        self._definitions = {definition.name: definition for definition in definitions}
        self._contracts: dict[str, AppAction[Any, Any]] = {}
        if len(self._definitions) != len(definitions):
            raise StateError("duplicate app action definitions")
        for definition in definitions:
            self.register(definition.name, cast(ActionHandler, definition.function))
            self._contracts[definition.name] = definition
            self._alias(definition)

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
            self.register(alias, cast(ActionHandler, definition.function))
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
        result = handler(state, self._python_payload(action_id, payload))
        if not isinstance(result, State):
            raise StateError("handler must return a State")
        return result

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

    def handlers(self) -> Mapping[str, ActionHandler]:
        return self._handlers.copy()
