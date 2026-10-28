"""What the bridge asks of the app it serves: the back stack's interface."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from pycompose.contract.registry_types import PropDef
from pycompose.core.action_binding import BindingSpec
from pycompose.state import State

__all__ = ["AppSession"]


class AppSession(Protocol):
    """What the bridge asks of the app it serves: the back stack's interface."""

    def validate_intents(
        self, intents: Mapping[str, Mapping[str, PropDef]]
    ) -> None: ...  # pragma: no cover - protocol declaration

    def contract(
        self, action_id: str
    ) -> Mapping[str, PropDef] | None: ...  # pragma: no cover - protocol declaration

    def __contains__(
        self, action_id: object
    ) -> bool: ...  # pragma: no cover - protocol declaration

    def declared(
        self, action_id: str, payload: Mapping[str, object]
    ) -> Mapping[str, object]: ...  # pragma: no cover - protocol declaration

    def dispatch(
        self, action_id: str, state: State, payload: Mapping[str, object]
    ) -> bool: ...  # pragma: no cover - protocol declaration

    def dispatch_binding(
        self, spec: BindingSpec, state: State, payload: Mapping[str, object]
    ) -> bool: ...  # pragma: no cover - protocol declaration

    def snapshot_state(
        self, previous: State | None
    ) -> State: ...  # pragma: no cover - protocol declaration

    def close(self) -> None: ...  # pragma: no cover - protocol declaration
