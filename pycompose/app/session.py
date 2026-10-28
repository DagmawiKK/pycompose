"""The back stack: a view model per screen, the session the bridge serves."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from pycompose.app.app import App, Destination
from pycompose.app.effects import Finish, Navigate
from pycompose.app.intents import intent_class
from pycompose.app.navigation import (
    NavOp,
    Pop,
    Push,
    Replace,
    Route,
    parse_route,
    route_key,
)
from pycompose.app.viewmodel import ViewModel, ViewModelHost, hosting
from pycompose.contract.catalog import REGISTRY
from pycompose.contract.registry_types import PropDef
from pycompose.core.action_binding import BindingSpec, check_payload
from pycompose.core.effect import Effect
from pycompose.core.props import JsonValue
from pycompose.errors import StateError
from pycompose.runtime import signal
from pycompose.runtime.scope import Report, Scope
from pycompose.state.state import State

__all__ = ["REFRESH", "NavigationSession"]

LOGGER = logging.getLogger(__name__)

REFRESH = "pycompose.refresh"
"""The data-free signal that state changed outside an intent: publish again."""


def _post_refresh() -> bool:
    """Ask the host to pull; False when no host took the signal."""
    try:
        delivered = signal.post(REFRESH)
    except Exception:  # a broken sink must not fail the work that changed state
        LOGGER.warning("the host's refresh signal failed", exc_info=True)
        return False
    if not delivered:
        # No host is listening, as in a test driving the bridge directly; the
        # next action publishes the change instead.
        LOGGER.debug("state changed with no host listening")
    return delivered


def _saved(model: ViewModel[Any] | None) -> JsonValue:
    """A view model's state as the saved stack carries it."""
    if model is None:
        return None
    return cast("JsonValue", type(model.state).codec.encode(model.state))


@dataclass
class _Entry:
    """One screen on the back stack."""

    route: Route
    key: str
    destination: Destination[Any]
    view_model: ViewModel[Any]
    saved: JsonValue = None
    """The saved state last published, to tell when a screen below changed it."""


class NavigationSession:
    """The app's back stack, behind the interface the bridge calls.

    The top entry's view model receives intents and lifecycle events, and its
    screen draws the snapshot. Pushing builds a view model from its destination;
    popping cancels the popped view model's work. Every entry's saved state is
    published, so process death restores the whole stack.

    Args:
        app: The app.
        container: The session's container, or None.
        route: The route the host restored or was opened with.
        restore: The saved state the host handed back, or empty.
        report: Receives each supervised task's failure.
        signal: Tells the host to pull again; posts a refresh by default.
            Returns False when no host took it, so the next change tries again.
    """

    def __init__(
        self,
        app: App,
        container: object | None,
        route: str,
        restore: str,
        report: Report,
        signal: Callable[[], bool | None] = _post_refresh,
    ) -> None:
        self._app = app
        self._container = container
        self._signal = signal
        self._dispatching = False
        self._pending = False
        self._effects: list[Effect] = []
        self._report = report
        self._scope = Scope("navigation", report)
        self._host = ViewModelHost(report, self._changed, self._navigate)
        self.entries: list[_Entry] = []
        built = False
        try:
            self._restore(restore)
            if not self.entries:
                self.entries.append(self._entry(app.route()))
            self._open(route)
            built = True
        finally:
            if not built:
                # A view model that failed to build must not leave its siblings'
                # work running behind a session nobody holds.
                self.close()

    def _entry(self, route: Route, saved: object = None) -> _Entry:
        destination = self._app.destination(route)
        with hosting(self._host):
            model = destination.view_model(self._container, route)
        if saved is not None:
            state = model.state
            codec = type(state).codec
            loaded = {f.name: getattr(state, f.name) for f in codec.fields if f.loaded}
            # Set directly: restoring is part of building, not a change to publish.
            model._state = codec.decode(saved).evolve(**loaded)
        return _Entry(route, route_key(route), destination, model)

    def _restore(self, restore: str) -> None:
        """Rebuild the saved stack, or none of it when any entry is unreadable."""
        if not restore:
            return
        try:
            for item in json.loads(restore)["stack"]:
                route = parse_route(json.dumps(item["route"]))
                if route is None:
                    raise StateError("saved route names no destination")
                self.entries.append(self._entry(route, item["state"]))
        except (StateError, ValueError, KeyError, TypeError):
            LOGGER.warning("saved state is unreadable; starting fresh")
            self.close()

    def _open(self, key: str) -> None:
        """Open a route the host named, if the app allows it from outside."""
        if key == self.top_key:
            return
        route = parse_route(key)
        if route is not None and type(route) in self._app.deep_links:
            self.entries.append(self._entry(route))

    @property
    def top_key(self) -> str:
        """The route on top, as the host keeps it.

        Returns:
            The top entry's route key.
        """
        return self.entries[-1].key

    def saved(self) -> str:
        """Return every entry's route and saved state, as a restore hands it back.

        Returns:
            The saved stack as JSON.
        """
        return json.dumps(self._stack())

    def _stack(self) -> dict[str, JsonValue]:
        stack = []
        for entry in self.entries:
            entry.saved = _saved(entry.view_model)
            stack.append({"route": json.loads(entry.key), "state": entry.saved})
        return {"stack": cast("list[JsonValue]", stack)}

    @property
    def top(self) -> ViewModel[Any]:
        """The view model of the screen on top.

        Returns:
            The top entry's view model.
        """
        return self.entries[-1].view_model

    def _changed(self, model: ViewModel[Any] | None = None) -> None:
        if self._dispatching or self._pending:
            return
        below = next((e for e in self.entries[:-1] if e.view_model is model), None)
        if below is not None and _saved(model) == below.saved:
            # A screen out of sight changed only what it reloads, never saves:
            # nothing on screen or in the saved stack differs, so no pass.
            return
        # Pending until the refresh arrives; a signal nobody took leaves the next
        # change free to try again.
        self._pending = self._signal() is not False

    def _take_effects(self) -> None:
        """Queue what every view model emitted, so effects keep the order emitted."""
        for entry in self.entries:
            self._effects.extend(entry.view_model.take_effects())

    def _navigate(self, operation: NavOp) -> None:
        self._take_effects()
        if isinstance(operation, Push):
            self.entries.append(self._entry(operation.route))
        elif isinstance(operation, Replace):
            self._close(self.entries.pop())
            self.entries.append(self._entry(operation.route))
        elif len(self.entries) > 1:
            self._close(self.entries.pop())
        else:
            self._effects.append(Finish().effect())
            return
        # The host keeps the route only to hand it back after process death.
        self._effects.append(Navigate(self.entries[-1].key).effect())
        self._changed()

    def _close(self, entry: _Entry) -> None:
        self._scope.spawn(entry.view_model.clear())

    def close(self) -> None:
        """Clear every screen's view model, top first, as the session ends."""
        for entry in reversed(self.entries):
            self._close(entry)
        self.entries = []

    def snapshot_state(self, previous: State | None) -> State:
        """Return the state the top screen draws now, as the next snapshot's source.

        Args:
            previous: The snapshot state before, or None for the first.

        Returns:
            The top screen with every entry's saved state and pending effects.
        """
        top = self.entries[-1]
        self._take_effects()
        effects, self._effects = self._effects, []
        return State(
            root=top.destination.screen(top.view_model.state),
            version=previous.version + 1 if previous is not None else 0,
            data=self._stack(),
            effects=tuple(effects),
        )

    def validate_intents(self, intents: Mapping[str, Mapping[str, PropDef]]) -> None:
        """Check that every intent a snapshot states is one this app defines.

        Args:
            intents: Each stated intent's payload contract, by wire name.

        Raises:
            StateError: If an intent is undefined or its contract differs.
        """
        for name, payload in intents.items():
            if self.contract(name) != dict(payload):
                raise StateError("undefined or mismatched intent", intent=name)

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
        """Report whether an event is one this session handles itself.

        Args:
            action_id: The event's id.

        Returns:
            True for the refresh signal and every host lifecycle event.
        """
        return action_id == REFRESH or action_id in REGISTRY.lifecycle

    def declared(
        self, action_id: str, payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        """Return a lifecycle event's fields as the host sent them.

        Args:
            action_id: The event's id.
            payload: Its fields, already checked against the host contract.

        Returns:
            The same fields.
        """
        del action_id
        return payload

    def dispatch_binding(
        self, spec: BindingSpec, state: State, payload: Mapping[str, object]
    ) -> State:
        """Run one intent on the top screen's view model and draw the result.

        Args:
            spec: The intent's class name, contract and bound fields.
            state: The snapshot state before.
            payload: The event's own fields.

        Returns:
            The next snapshot state.

        Raises:
            StateError: If the intent cannot be built from its fields.
            Exception: Whatever the view model's handler raised, once reported.
        """
        cls = intent_class(spec.handler_id)
        if cls is None:
            raise StateError("unknown intent", intent=spec.handler_id)
        check_payload(payload, spec.event_fields)
        complete = {**spec.bound, **payload}
        check_payload(complete, spec.payload)
        intent = cls.codec.decode(complete)
        self._dispatching = True
        try:
            self.top.on_intent(intent)
        except Exception as exc:
            # Supervised like launched work: reported, then refused as a pass.
            self._report(f"intent {cls.__qualname__}", exc)
            raise
        finally:
            self._dispatching = False
        return self.snapshot_state(state)

    def dispatch(self, action_id: str, state: State, payload: Any = None) -> State:
        """Handle the refresh signal and the host's lifecycle events.

        Args:
            action_id: The event's id.
            state: The snapshot state before.
            payload: The event's fields.

        Returns:
            The next snapshot state.

        Raises:
            StateError: For an event this session does not handle.
        """
        self._dispatching = True
        try:
            if action_id == REFRESH:
                self._pending = False
            elif action_id == "onBackRequested":
                if not self.top.on_back():
                    self._navigate(Pop())
            elif action_id == "onRouteChanged":
                self._open(str((payload or {}).get("route", "")))
            elif action_id == "onResume":
                self.top.on_resume()
            elif action_id == "onPause":
                self.top.on_pause()
            elif action_id not in REGISTRY.lifecycle:
                raise StateError("unknown action", action_id=action_id)
        finally:
            self._dispatching = False
        return self.snapshot_state(state)
