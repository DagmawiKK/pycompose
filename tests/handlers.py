"""Named handlers over State: the session a bridge test serves.

The bridge asks its session to handle each action and validate each snapshot's
intents. These tests are about the bridge, so the session is the smallest one
that answers: a handler per registry action name, and no intents.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from pycompose.contract.registry_types import PropDef
from pycompose.core.action_binding import BindingSpec
from pycompose.errors import StateError
from pycompose.state import State

Handler = Callable[[State, Any], State]


class Handlers:
    """A handler per action name, standing in for the app's back stack."""

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}
        self.closed = False

    def register(self, name: str, handler: Handler) -> None:
        self._handlers[name] = handler

    def validate_intents(self, intents: Mapping[str, Mapping[str, PropDef]]) -> None:
        if intents:
            raise StateError("these tests state no intents")

    def contract(self, action_id: str) -> Mapping[str, PropDef] | None:
        del action_id
        return None

    def __contains__(self, action_id: object) -> bool:
        return action_id in self._handlers

    def declared(
        self, action_id: str, payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        del action_id
        return payload

    def dispatch(
        self, action_id: str, state: State, payload: Mapping[str, object]
    ) -> State:
        if action_id not in self._handlers:
            raise StateError("unknown action", action_id=action_id)
        return self._handlers[action_id](state, payload)

    def dispatch_binding(
        self, spec: BindingSpec, state: State, payload: Mapping[str, object]
    ) -> State:
        del state, payload
        raise StateError("these tests state no intents", intent=spec.handler_id)

    def close(self) -> None:
        self.closed = True
