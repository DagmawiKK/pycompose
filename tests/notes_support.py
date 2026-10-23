"""Shared helpers and the app fixture for the bundled notes example."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pycompose import AppContext, install_context
from pycompose.bridge import BridgeSurface
from pycompose.core.props import to_camel_case
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
        """Start a session the way ChaquopyBridge would.

        Args:
            app: The app entrypoint module.
            route: The route the host restored.
            restore: Data the host saved from a previous process.
            follow_navigation: Echo navigate effects back as the host does. Off
                to observe what an action asks for without moving the screen.
            repo: Where the notes live. Defaults to an in-memory store, so no test
                touches a file and the data layer is never on the path.
        """
        from notes_app.container import AppContainer
        from notes_app.domain import Notes

        self.follow_navigation = follow_navigation
        self.repo: Any = repo if repo is not None else a_store()
        self.container = AppContainer(Notes(self.repo))
        # A real session installs all of this while resolving the entry
        # object. A test driving the surface directly stands in for one, so it
        # says so once, in one place.
        app.actions.install_container(self.container)
        app.actions.install_view(app.app.session_view)
        install_context(
            AppContext(
                actions=app.actions,
                container=self.container,
                notes=self.container.notes,
            )
        )
        self._bridge = BridgeSurface(
            Store(app.app.build(route=route or "notes", restore=restore)),
            app.actions,
        )

    @property
    def titles(self) -> list[str]:
        """Return the note titles held, newest first.

        Returns:
            Every stored title.
        """
        return [
            held.title
            for held in sorted(self.repo.load(), key=lambda n: n.id, reverse=True)
        ]

    def title_of(self, note_id: int) -> str:
        """Return one note's stored title.

        Args:
            note_id: Identity to look for.

        Returns:
            The stored title.

        Raises:
            AssertionError: If no such note is held.
        """
        for held in self.repo.load():
            if held.id == note_id:
                return held.title
        raise AssertionError(f"no held note with id {note_id}")

    @property
    def error(self) -> str:
        """Return the worker's last diagnostic.

        Returns:
            The error text, or an empty string.
        """
        return self._bridge.expose_latest_error() or ""

    def snapshot(self) -> dict[str, Any]:
        """Return the latest snapshot, failing loudly if there is none.

        Returns:
            The parsed snapshot.
        """
        source = self._bridge.expose_latest_snapshot()
        assert source is not None, self.error
        return json.loads(source)

    def tap(
        self, handler: str, bound: Mapping[str, Any] | None = None, **event: Any
    ) -> None:
        """Deliver one action envelope to the control a handler is bound to.

        Args:
            handler: The action's function name.
            bound: The values the control binds, when several controls bind
                one handler; None for the only control bound to it.
            **event: Event fields the handler declares as unfilled.
        """
        action_id = self._id_for(handler, bound)
        self._bridge.accept_action(
            json.dumps({"actionId": action_id, "payload": event})
        )
        self._follow_navigation()

    def lifecycle(self, event: str, **payload: Any) -> None:
        """Deliver one host lifecycle event by its camelCase name.

        Args:
            event: The lifecycle event name.
            **payload: Fields the event declares.
        """
        self._bridge.accept_action(json.dumps({"actionId": event, "payload": payload}))
        self._follow_navigation()

    def follow(self, destination: str) -> None:
        """Honour a navigate effect the way the host does.

        The host no longer rebuilds Python for a route change. It echoes the new
        route back as an ordinary lifecycle action and lets the app decide what
        that route means.

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

    def _id_for(self, handler: str, bound: Mapping[str, Any] | None) -> str:
        """Return the binding a control was given in the current snapshot.

        A control is named by its handler, and by the values it binds when
        several controls bind one handler.

        Args:
            handler: The action's function name.
            bound: The values the control binds, or None for the only one.

        Returns:
            The binding id.

        Raises:
            AssertionError: Unless exactly one live binding matches.
        """
        bindings = (self.snapshot().get("metadata") or {}).get("actionBindings", {})
        wanted = (
            None
            if bound is None
            else {to_camel_case(key): value for key, value in bound.items()}
        )
        matches = [
            binding_id
            for binding_id, contract in bindings.items()
            if contract["handlerId"].rpartition(".")[2] == handler
            and (wanted is None or contract["bound"] == wanted)
        ]
        if len(matches) != 1:
            raise AssertionError(
                f"{len(matches)} live bindings for {handler} {bound}: {list(bindings)}"
            )
        return cast("str", matches[0])


def data(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return the app data a snapshot published.

    Args:
        snapshot: A parsed snapshot.

    Returns:
        The published data.
    """
    return snapshot["metadata"]["data"]


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
    for held in host.repo.load():
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
