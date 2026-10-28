"""One destination's view model, served to the bridge as its action registry."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from typing import Any

from pycompose import async_task
from pycompose.app.app import App
from pycompose.app.intents import intent_class
from pycompose.app.viewmodel import ViewModel, ViewModelHost, hosting
from pycompose.contract.registry_types import PropDef
from pycompose.core.action_binding import BindingSpec
from pycompose.errors import StateError
from pycompose.runtime.scope import Report
from pycompose.state.actions import Actions
from pycompose.state.state import State

__all__ = ["REFRESH", "ScreenSession"]

LOGGER = logging.getLogger(__name__)

REFRESH = "pycompose.refresh"
"""The data-free signal that state changed outside an intent: publish again."""


def _post_refresh() -> None:
    try:
        async_task.post(REFRESH, "{}")
    except StateError:
        # No host is listening, as in a test driving the bridge directly; the
        # next action publishes the change instead.
        LOGGER.debug("state changed with no host listening")


class ScreenSession(Actions):
    """A destination's view model, behind the registry interface the bridge calls.

    Intents decode against their own classes, run on the view model, and the
    screen draws its state into the next snapshot. A change made outside an
    intent -- by a task the view model launched -- sends one refresh signal
    until that refresh is handled.

    Args:
        app: The app whose start destination this is.
        container: The session's container, or None.
        restore: The saved state the host handed back, or empty.
        report: Receives each supervised task's failure.
        signal: Tells the host to pull again; posts a refresh by default.
    """

    def __init__(
        self,
        app: App,
        container: object | None,
        restore: str,
        report: Report,
        signal: Callable[[], None] = _post_refresh,
    ) -> None:
        super().__init__()
        self._destination = app.start
        self._signal = signal
        self._dispatching = False
        self._pending = False
        with hosting(ViewModelHost(report, self._changed)):
            factory = self._destination.view_model
            self.view_model: ViewModel[Any] = (
                factory(container) if container is not None else factory()
            )
        self._restore(restore)

    def _restore(self, restore: str) -> None:
        if not restore:
            return
        state = self.view_model.state
        try:
            saved = type(state).codec.decode(json.loads(restore))
        except (StateError, ValueError):
            LOGGER.warning("saved state is unreadable; starting fresh")
            return
        loaded = {
            f.name: getattr(state, f.name) for f in type(state).codec.fields if f.loaded
        }
        # Set directly: restoring is part of building, not a change to publish.
        self.view_model._state = saved.evolve(**loaded)

    def _changed(self) -> None:
        if self._dispatching or self._pending:
            return
        self._pending = True
        self._signal()

    def snapshot_state(self, previous: State | None) -> State:
        """Return the state the screen draws now, as the next snapshot's source.

        Args:
            previous: The snapshot state before, or None for the first.

        Returns:
            The view model's state drawn by its screen, with emitted effects.
        """
        state = self.view_model.state
        return State(
            root=self._destination.screen(state),
            version=previous.version + 1 if previous is not None else 0,
            app=state,
            effects=self.view_model.take_effects(),
        )

    def contract(self, action_id: str) -> Mapping[str, PropDef] | None:
        """Return the fields of the intent class a wire name names.

        Args:
            action_id: The intent's wire name.

        Returns:
            Its contract, or None when no intent has that name.
        """
        cls = intent_class(action_id)
        return cls.contract() if cls is not None else None

    def __contains__(self, action_id: object) -> bool:
        """Report whether an event names this session's refresh signal.

        Args:
            action_id: The event's id.

        Returns:
            True only for the refresh signal.
        """
        return action_id == REFRESH

    def dispatch_binding(
        self, spec: BindingSpec, state: State, payload: Mapping[str, object]
    ) -> State:
        """Run one intent on the view model and draw the result.

        Args:
            spec: The intent's class name, contract and bound fields.
            state: The snapshot state before.
            payload: The event's own fields.

        Returns:
            The next snapshot state.

        Raises:
            StateError: If the intent cannot be built from its fields.
        """
        cls = intent_class(spec.handler_id)
        if cls is None:
            raise StateError("unknown intent", intent=spec.handler_id)
        intent = cls.codec.decode({**spec.bound, **payload})
        self._dispatching = True
        try:
            self.view_model.on_intent(intent)
        finally:
            self._dispatching = False
        return self.snapshot_state(state)

    def dispatch(self, action_id: str, state: State, payload: Any = None) -> State:  # noqa: ARG002 -- the refresh signal carries no data
        """Handle the refresh signal: draw the state as it is now.

        Args:
            action_id: The event's id.
            state: The snapshot state before.
            payload: Unused; the refresh signal carries no data.

        Returns:
            The next snapshot state.

        Raises:
            StateError: For anything but the refresh signal.
        """
        if action_id != REFRESH:
            raise StateError("unknown action", action_id=action_id)
        self._pending = False
        return self.snapshot_state(state)
