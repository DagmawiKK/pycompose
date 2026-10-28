"""Shared helpers and the app fixture for the bundled notes example."""

from __future__ import annotations

import asyncio
import atexit
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pycompose.app import to_thread
from pycompose.app.session import REFRESH, NavigationSession
from pycompose.bridge import BridgeSurface
from pycompose.core.props import to_camel_case
from pycompose.runtime.loop import LoopThread
from pycompose.state import Store

if TYPE_CHECKING:
    from types import ModuleType

APP = Path(__file__).resolve().parents[1] / "examples" / "notes" / "app"


SEEDED = [
    (1, "Welcome", "This app is written entirely in Python."),
    (2, "Try it", "Tap a note to edit it, or add one with the New button."),
]


def a_store(notes: Any = ...) -> Any:
    """Return an in-memory store, seeded unless told otherwise.

    Args:
        notes: What it should hold. Defaults to the two seeded notes; pass a list
            for an exact inventory.

    Returns:
        A memory-backed note repository.
    """
    from notes_app.data.notes_repo import MemoryNotesRepo
    from notes_app.domain.models import Note

    return MemoryNotesRepo(
        [Note(*held) for held in (SEEDED if notes is ... else notes)]
    )


def load_notes_app() -> ModuleType:
    """Import the Notes app exactly as the Android worker does.

    Returns:
        The app package's entrypoint module.
    """
    sys.path.insert(0, str(APP))
    try:
        import main as notes

        return notes
    finally:
        sys.path.remove(str(APP))


_LOOP: LoopThread | None = None
"""One loop thread for every host, as one process has one."""


def _loop() -> LoopThread:
    global _LOOP  # noqa: PLW0603 -- one loop thread per test process
    if _LOOP is None:
        _LOOP = LoopThread(lambda scope, error: FAILURES.append(f"{scope}: {error}"))
        atexit.register(_end, _LOOP)
    return _LOOP


_HOSTS: list[Host] = []
"""Every host started, kept so each is closed rather than collected mid-task."""


def _end(loop: LoopThread) -> None:
    """Close every host's session, then stop the loop, as a process ends."""
    for host in _HOSTS:
        loop.call(host._bridge.close)
    loop.stop()


FAILURES: list[str] = []
"""Every launched task that failed, on any host."""


class Host:
    """A stand-in for the Android host: starts a session and feeds it actions."""

    def __init__(
        self,
        app: ModuleType,
        *,
        route: str = "",
        restore: str = "",
        follow_navigation: bool = True,
        repo: Any = None,
    ) -> None:
        """Start a session on the loop thread, the way ChaquopyBridge would.

        Args:
            app: The app entrypoint module.
            route: The route the host restored, or empty for the start route.
            restore: Data the host saved from a previous process.
            follow_navigation: Echo navigate effects back as the host does. Off
                to observe what an action asks for without moving the screen.
            repo: Where the notes live. Defaults to an in-memory store, so no test
                touches a file and the data layer is never on the path.
        """
        from notes_app.container import AppContainer

        self.follow_navigation = follow_navigation
        self.repo: Any = repo if repo is not None else a_store()
        self.container = AppContainer(self.repo)
        self._refresh = False

        def start() -> BridgeSurface:
            self.session = NavigationSession(
                app.app,
                self.container,
                route,
                restore,
                report=lambda scope, error: FAILURES.append(f"{scope}: {error}"),
                signal=self._signalled,
            )
            return BridgeSurface(Store(self.session.snapshot_state(None)), self.session)

        self._bridge = _loop().call(start)
        _HOSTS.append(self)

    def _signalled(self) -> None:
        self._refresh = True

    def _deliver(self, envelope: dict[str, Any]) -> None:
        """Run one action, then the work it woke, then any refresh it signalled.

        The host runs the effects of every snapshot it pulls, so each one's are
        kept in :attr:`ran`.
        """
        self.ran: list[tuple[str, dict[str, Any]]] = []
        _loop().call(self._bridge.accept_action, json.dumps(envelope))
        self.ran += effects(self.snapshot())
        _loop().call(lambda: None)
        while self._refresh:
            self._refresh = False
            _loop().call(
                self._bridge.accept_action,
                json.dumps({"intent": REFRESH, "payload": {}}),
            )
            self.ran += effects(self.snapshot())
            _loop().call(lambda: None)

    def settle_storage(self) -> None:
        """Wait until every write the app asked storage for has run."""

        async def drained() -> None:
            await to_thread("storage", lambda: None)

        asyncio.run_coroutine_threadsafe(drained(), _loop().loop).result(timeout=10)

    def envelope(self) -> str:
        """Return the whole snapshot envelope the host would pull first.

        Returns:
            The envelope's JSON.
        """
        return str(_loop().call(self._bridge.expose_envelope, -1))

    @property
    def titles(self) -> list[str]:
        """Return the note titles held, newest first.

        Returns:
            Every stored title.
        """
        return [held.title for held in self.container.notes.list()]

    def title_of(self, note_id: int) -> str:
        """Return one note's stored title.

        Args:
            note_id: Identity to look for.

        Returns:
            The stored title.

        Raises:
            AssertionError: If no such note is held.
        """
        for held in self.container.notes.list():
            if held.id == note_id:
                return held.title
        raise AssertionError(f"no held note with id {note_id}")

    @property
    def error(self) -> str:
        """Return the worker's last diagnostic.

        Returns:
            The error text, or an empty string.
        """
        return _loop().call(self._bridge.expose_latest_error) or ""

    def snapshot(self) -> dict[str, Any]:
        """Return the latest snapshot, failing loudly if there is none.

        Returns:
            The parsed snapshot.
        """
        source = _loop().call(self._bridge.expose_latest_snapshot)
        assert source is not None, self.error
        return json.loads(source)

    def tap(
        self, handler: str, bound: Mapping[str, Any] | None = None, **event: Any
    ) -> None:
        """Deliver one action envelope to the control carrying an intent.

        Args:
            handler: The intent's class name.
            bound: The values the control binds, when several controls bind
                one handler; None for the only control bound to it.
            **event: Event fields the handler declares as unfilled.
        """
        intent = self.intent_for(handler, bound)
        self._deliver({**intent, "payload": event})
        self._follow_navigation()

    def lifecycle(self, event: str, **payload: Any) -> None:
        """Deliver one host lifecycle event by its camelCase name.

        Args:
            event: The lifecycle event name.
            **payload: Fields the event declares.
        """
        self._deliver({"intent": event, "payload": payload})
        self._follow_navigation()

    def follow(self, destination: str) -> None:
        """Honour a navigate effect the way the host does.

        The host echoes the route back as a lifecycle action; Python already
        moved its back stack, so the echo of the screen on top changes nothing.

        Args:
            destination: The route carried by the snapshot's navigate effect.
        """
        self.lifecycle("onRouteChanged", route=destination)

    def _follow_navigation(self) -> None:
        """Echo any requested navigation, exactly as the host would."""
        if not self.follow_navigation:
            return
        for kind, body in effects(self.snapshot()):
            if kind == "navigate":
                self.lifecycle("onRouteChanged", **body)

    def intent_for(
        self, handler: str, bound: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        """Return the intent a control carries in the current snapshot.

        A control is named by its intent's class, and by the values it binds
        when several controls carry one intent class.

        Args:
            handler: The intent's class name.
            bound: The values the control binds, or None for the only one.

        Returns:
            The intent object, exactly as the control carries it.

        Raises:
            AssertionError: Unless exactly one distinct live intent matches.
        """
        wanted = (
            None
            if bound is None
            else {to_camel_case(key): value for key, value in bound.items()}
        )
        matches = [
            intent
            for intent in live_intents(self.snapshot())
            if intent["intent"].rpartition(".")[2] == handler
            and (wanted is None or intent["fields"] == wanted)
        ]
        if len(matches) != 1:
            raise AssertionError(f"{len(matches)} live intents for {handler} {bound}")
        return matches[0]


def live_intents(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Return every distinct intent the snapshot's controls carry.

    Args:
        snapshot: A parsed snapshot.

    Returns:
        The intents, in the order the walk meets them.
    """
    found: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if set(value) == {"fields", "intent"}:
                if value not in found:
                    found.append(value)
                return
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(snapshot["root"])
    return found


def data(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return the saved state of the screen on top.

    Args:
        snapshot: A parsed snapshot.

    Returns:
        The top entry's saved state.
    """
    return snapshot["metadata"]["data"]["stack"][-1]["state"]


def stack(snapshot: dict[str, Any]) -> list[str]:
    """Return the back stack's route classes, bottom first.

    Args:
        snapshot: A parsed snapshot.

    Returns:
        Each entry's route class name.
    """
    return [
        entry["route"]["route"].rpartition(".")[2]
        for entry in snapshot["metadata"]["data"]["stack"]
    ]


def titles_of(host: Any) -> list[str]:
    """Return the titles held by a host started in one expression.

    Args:
        host: The host.

    Returns:
        Every stored title, newest first.
    """
    return host.titles


def held_of(host: Any, note_id: int) -> Any:
    """Return one stored note by identity.

    Args:
        host: The running host.
        note_id: The note to find.

    Returns:
        The stored note.

    Raises:
        AssertionError: If no such note is held.
    """
    for held in host.container.notes.list():
        if held.id == note_id:
            return held
    raise AssertionError(f"no held note {note_id}")


def effects(snapshot: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Return the effects a snapshot asked the host to run, in order.

    Args:
        snapshot: A parsed snapshot.

    Returns:
        Each effect's kind and payload.
    """
    return [
        (effect["kind"], effect.get("payload", {}))
        for effect in (snapshot.get("metadata") or {}).get("effects", [])
    ]


def nodes(snapshot: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """Return the props of every node of one component type.

    Args:
        snapshot: A parsed snapshot.
        kind: The component type to collect.

    Returns:
        Each matching node's props, in tree order.
    """
    found: list[dict[str, Any]] = []
    pending = [snapshot["root"]]
    while pending:
        node = pending.pop(0)
        if node["type"] == kind:
            found.append(node["props"])
        pending = node.get("children", []) + pending
    return found
