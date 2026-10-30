"""A snapshot: the drawn tree a pass produced and the effects it requests.

The emitter turns one into the wire envelope; the back stack keeps the current
one in a :class:`SnapshotStore`. Effects are one-shot requests the host runs
once, in order, and then drops.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

from pycompose.errors import IrValidationError, StateError
from pycompose.model.canonical import (
    FrozenJsonValue,
    check_json,
    freeze_json,
    thaw_json,
)
from pycompose.model.nodes.node import Node
from pycompose.model.nodes.props import JsonValue

__all__ = ["Effect", "Snapshot", "SnapshotStore"]

_KIND = re.compile(r"[A-Za-z][A-Za-z0-9]*")


@dataclass(frozen=True, slots=True)
class Effect:
    """One request for the host to execute exactly once, in order.

    An effect is data, not state: it describes something the app wants the host
    to do, and the host drops it after acting. Anything that must survive a
    configuration change belongs in the app's state instead.

    Attributes:
        kind: Registered effect kind, such as ``navigate``.
        payload: Frozen JSON values keyed by wire field name.
    """

    kind: str
    payload: Mapping[str, FrozenJsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Freeze the payload and reject a malformed kind.

        Raises:
            IrValidationError: If the kind or payload is not usable data.
        """
        if not isinstance(self.kind, str) or _KIND.fullmatch(self.kind) is None:
            raise IrValidationError("invalid effect kind", kind=str(self.kind))
        if not isinstance(self.payload, Mapping):
            raise IrValidationError("effect payload must be a mapping")
        frozen = freeze_json(self.payload)
        if not isinstance(frozen, Mapping):
            raise IrValidationError("effect payload must be a mapping")
        object.__setattr__(self, "payload", MappingProxyType(dict(frozen)))

    def to_wire(self) -> dict[str, JsonValue]:
        """Return the JSON-ready envelope member for this request.

        Returns:
            An object with ``kind`` and ``payload``, detached from this value.
        """
        return {"kind": self.kind, "payload": thaw_json(dict(self.payload))}


@dataclass(frozen=True, slots=True)
class Snapshot:
    """The drawn tree a pass produced, with what it asks of the host.

    App data is UI-affecting JSON only; it stays inside Python and never
    crosses the boundary, which carries the emitted IR alone. The app's own
    typed data is its :class:`~pycompose.state.AppState`; this is what a pass
    drew from it.

    Attributes:
        root: Composable declaration rebuilt into the next snapshot.
        version: App-defined counter, not a schema or library version.
        data: App-owned JSON values describing the UI, such as a task list.
        effects: One-shot requests for the host, executed once in order.
        schema_version: Schema version this app requires.
        min_library_version: Library version this app requires.
    """

    root: Node
    version: int = 0
    data: Mapping[str, JsonValue | FrozenJsonValue] | None = None
    effects: tuple[Effect, ...] = ()
    schema_version: str | None = None
    min_library_version: str | None = None

    def __post_init__(self) -> None:
        """Validate the snapshot's own invariants and freeze app data.

        Raises:
            StateError: If a field is not a valid snapshot value.
        """
        if not isinstance(self.root, Node):
            raise StateError("snapshot.root must be a Node instance")
        if not isinstance(self.version, int) or self.version < 0:
            raise StateError("snapshot.version must be a non-negative int")
        if not isinstance(self.effects, tuple) or any(
            not isinstance(effect, Effect) for effect in self.effects
        ):
            raise StateError("snapshot.effects must be a tuple of Effect instances")
        if self.data is not None:
            if not isinstance(self.data, Mapping):
                raise StateError("snapshot.data must be a mapping or None")
            try:
                check_json(self.data)
                object.__setattr__(
                    self,
                    "data",
                    cast("Mapping[str, FrozenJsonValue]", freeze_json(self.data)),
                )
            except IrValidationError as exc:
                raise StateError("snapshot.data must be JSON-compatible") from exc
        if self.schema_version is not None and (
            not isinstance(self.schema_version, str) or not self.schema_version
        ):
            raise StateError("snapshot.schema_version must be a non-empty string")
        if self.min_library_version is not None and (
            not isinstance(self.min_library_version, str)
            or not self.min_library_version
        ):
            raise StateError("snapshot.min_library_version must be a non-empty string")


class SnapshotStore:
    """Mutable holder of the current snapshot."""

    def __init__(self, initial: Snapshot) -> None:
        if not isinstance(initial, Snapshot):
            raise StateError("initial must be a Snapshot")
        self._state = initial

    @property
    def value(self) -> Snapshot:
        return self._state

    def mutate(self, fn: Callable[[Snapshot], Snapshot]) -> Snapshot:
        if not callable(fn):
            raise StateError("fn must be callable")
        new_state = fn(self._state)
        if not isinstance(new_state, Snapshot):
            raise StateError("mutate must return a Snapshot")
        self._state = new_state
        return self._state

    def request_rebuild(self, new_state: Snapshot) -> None:
        if not isinstance(new_state, Snapshot):
            raise StateError("new_state must be a Snapshot")
        if self._state is new_state or self._state == new_state:
            return
        self._state = new_state
