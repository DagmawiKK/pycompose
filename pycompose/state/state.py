"""Frozen State and mutable Store."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pycompose.core.node import Node
from pycompose.errors import StateError

__all__ = ["State", "Store"]


@dataclass(frozen=True, slots=True)
class State:
    """Immutable application state snapshot."""

    root: Node
    version: int = 0
    schema_version: str | None = None
    min_library_version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.root, Node):
            raise StateError("state.root must be a Node instance")
        if not isinstance(self.version, int) or self.version < 0:
            raise StateError("state.version must be a non-negative int")
        if self.schema_version is not None and (
            not isinstance(self.schema_version, str) or not self.schema_version
        ):
            raise StateError("state.schema_version must be a non-empty string")
        if self.min_library_version is not None and (
            not isinstance(self.min_library_version, str)
            or not self.min_library_version
        ):
            raise StateError("state.min_library_version must be a non-empty string")


class Store:
    """Mutable holder of current state."""

    def __init__(self, initial: State) -> None:
        if not isinstance(initial, State):
            raise StateError("initial must be a State instance")
        self._state = initial

    @property
    def value(self) -> State:
        return self._state

    def mutate(self, fn: Callable[[State], State]) -> State:
        if not callable(fn):
            raise StateError("fn must be callable")
        new_state = fn(self._state)
        if not isinstance(new_state, State):
            raise StateError("mutate must return a State")
        self._state = new_state
        return self._state

    def request_rebuild(self, new_state: State) -> None:
        if not isinstance(new_state, State):
            raise StateError("new_state must be a State instance")
        if self._state is new_state or self._state == new_state:
            return
        self._state = new_state
