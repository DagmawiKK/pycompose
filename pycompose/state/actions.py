"""Action registry."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from pycompose.errors import StateError
from pycompose.state.state import State

__all__ = ["ActionHandler", "Actions"]

ActionHandler = Callable[[State, Any], State]


class Actions:
    def __init__(self) -> None:
        self._handlers: dict[str, ActionHandler] = {}

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
        result = handler(state, payload)
        if not isinstance(result, State):
            raise StateError("handler must return a State")
        return result

    def handlers(self) -> Mapping[str, ActionHandler]:
        return self._handlers.copy()
