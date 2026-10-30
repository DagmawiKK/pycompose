"""Frozen State and mutable Store."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import cast

from pycompose.errors import IrValidationError, StateError
from pycompose.model.canonical import (
    FrozenJsonValue,
    check_json,
    freeze_json,
)
from pycompose.model.nodes.effect import Effect
from pycompose.model.nodes.node import Node
from pycompose.model.nodes.props import JsonValue
from pycompose.state.app_state import AppState

__all__ = ["State", "Store"]


@dataclass(frozen=True, slots=True)
class State:
    """Immutable application state snapshot.

    App data is UI-affecting JSON only; it stays inside Python and never
    crosses the boundary, which carries the emitted IR alone.

    Attributes:
        root: Composable declaration rebuilt into the next snapshot.
        version: App-defined counter, not a schema or library version.
        data: App-owned JSON values describing the UI, such as a task list.
        effects: One-shot requests for the host, executed once in order.
        schema_version: Schema version this app requires.
        min_library_version: Library version this app requires.
        app: The session shell — the small state every screen needs. Encoded
            into ``data`` on the way in. Supply either this or ``data``, never
            both.
        slices: Feature state, keyed by partition name, encoded into ``data``
            beside the shell. Attaching only the slices a screen needs is what
            keeps a keystroke from re-encoding the whole app.
    """

    root: Node
    version: int = 0
    data: Mapping[str, JsonValue | FrozenJsonValue] | None = None
    effects: tuple[Effect, ...] = ()
    schema_version: str | None = None
    min_library_version: str | None = None
    app: AppState | None = None
    slices: Mapping[str, AppState] = field(default_factory=dict)

    def _validate_parts(self) -> None:
        """Check the shell and slices are well formed, then publish them.

        Raises:
            StateError: If any part is invalid, or ``data`` was also supplied.
        """
        if not isinstance(self.slices, Mapping):
            raise StateError("state.slices must be a mapping")
        if self.app is not None and not isinstance(self.app, AppState):
            raise StateError("state.app must be an AppState instance")
        for name, value in self.slices.items():
            if not isinstance(name, str) or not name:
                raise StateError("slice names must be nonempty strings")
            if not isinstance(value, AppState):
                raise StateError(f"state.slices[{name!r}] must be an AppState instance")
        if self.data is not None:
            raise StateError("state cannot carry both data and app/slices")
        object.__setattr__(self, "data", self._encode_parts())

    def _encode_parts(self) -> Mapping[str, JsonValue]:
        """Return the shell and every attached slice as one JSON object.

        Returns:
            The published data.

        Raises:
            StateError: If two parts claim the same top-level key.
        """
        encoded: dict[str, JsonValue] = {}
        owners: dict[str, str] = {}
        parts = [("shell", self.app)] if self.app is not None else []
        parts += list(self.slices.items())
        for name, value in parts:
            for key in value.codec.encode(value):
                if key in owners:
                    raise StateError(
                        f"'{key}' is claimed by both {owners[key]!r} and {name!r}"
                    )
                owners[key] = name
            encoded.update(value.codec.encode(value))
        return encoded

    def partitions(self) -> Mapping[str, tuple[str, ...]]:
        """Return the top-level keys each part of this state owns.

        Knowing which keys belong to the shell and which to a feature slice is
        what lets a host save the small durable part and rebuild the rest, rather
        than putting the whole app through a Bundle.

        Returns:
            Partition name to the keys it owns, always including ``"shell"``.
        """
        parts: dict[str, tuple[str, ...]] = {}
        if self.app is not None:
            parts["shell"] = tuple(sorted(self.app.codec.encode(self.app)))
        for name, value in self.slices.items():
            parts[name] = tuple(sorted(value.codec.encode(value)))
        return parts

    def __post_init__(self) -> None:
        """Validate the snapshot's own invariants and freeze app data.

        Raises:
            StateError: If a field is not a State instance value.
        """
        if not isinstance(self.root, Node):
            raise StateError("state.root must be a Node instance")
        if not isinstance(self.version, int) or self.version < 0:
            raise StateError("state.version must be a non-negative int")
        if not isinstance(self.effects, tuple) or any(
            not isinstance(effect, Effect) for effect in self.effects
        ):
            raise StateError("state.effects must be a tuple of Effect instances")
        if self.app is not None or self.slices:
            self._validate_parts()
        if self.data is not None:
            if not isinstance(self.data, Mapping):
                raise StateError("state.data must be a mapping or None")
            try:
                check_json(self.data)
                object.__setattr__(
                    self,
                    "data",
                    cast("Mapping[str, FrozenJsonValue]", freeze_json(self.data)),
                )
            except IrValidationError as exc:
                raise StateError("state.data must be JSON-compatible") from exc
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
