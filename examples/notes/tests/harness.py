"""Drive the Notes app the way the Android host does, without a device.

Every intent is read out of the snapshot's own controls rather than guessed,
which is exactly what the renderer does.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(ROOT))

from pycompose import AppContext, install_context  # noqa: E402
from pycompose.bridge import BridgeSurface  # noqa: E402
from pycompose.core.props import to_camel_case  # noqa: E402
from pycompose.state import Store  # noqa: E402


class Host:
    """A stand-in for the Android host: starts a session and feeds it actions."""

    def __init__(
        self,
        entrypoint: Any,
        *,
        route: str = "notes",
        restore: str = "",
        follow_navigation: bool = True,
    ) -> None:
        """Start a session the way ChaquopyBridge would.

        Args:
            entrypoint: The app module.
            route: The route the host restored.
            restore: Data the host saved from a previous process.
            follow_navigation: Echo navigate effects back as the host does.
        """
        self.follow_navigation = follow_navigation
        # A real session builds the app's container and installs the context
        # while resolving the app's factory, before anything renders: the views
        # read both of them from there rather than being handed them. This
        # harness drives the surface directly, so it stands in for that here,
        # once, and hands the same container to ``build``.
        container = entrypoint.container()
        entrypoint.actions.install_container(container)
        install_context(
            AppContext(
                actions=entrypoint.actions,
                container=container,
                notes=container.notes,
            )
        )
        self.container = container
        self._bridge = BridgeSurface(
            Store(entrypoint.build(route=route, restore=restore, container=container)),
            entrypoint.actions,
        )

    @property
    def titles(self) -> list[str]:
        """Return the note titles held, newest first.

        The notes live in the repository rather than in the published shell, so
        this reads them where they are instead of looking for them in a
        snapshot -- which is the seam the whole data layer exists for.

        Returns:
            The titles, newest first.
        """
        return [note.title for note in self.container.notes.list()]

    @property
    def error(self) -> str:
        """Return the worker's last diagnostic.

        Returns:
            The error text, or an empty string.
        """
        return self._bridge.expose_latest_error() or ""

    def snapshot(self) -> dict[str, Any]:
        """Return the latest snapshot.

        Returns:
            The parsed snapshot, failing the test if the worker published none.
        """
        source = self._bridge.expose_latest_snapshot()
        assert source is not None, self.error
        return cast("dict[str, Any]", json.loads(source))

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
        intent = self._intent_for(handler, bound)
        self._bridge.accept_action(json.dumps({**intent, "payload": event}))
        self._follow_navigation()

    def lifecycle(self, event: str, **payload: Any) -> None:
        """Deliver one host lifecycle event by its camelCase name.

        Args:
            event: The lifecycle event name.
            **payload: Fields the event declares.
        """
        self._bridge.accept_action(json.dumps({"intent": event, "payload": payload}))
        self._follow_navigation()

    def _follow_navigation(self) -> None:
        """Echo any requested navigation, exactly as the host would.

        The host does not rebuild Python for a route change. It records the new
        route and hands it back as an ordinary action.
        """
        if not self.follow_navigation:
            return
        for kind, body in effects(self.snapshot()):
            if kind == "navigate":
                self.lifecycle("onRouteChanged", **body)

    def follow(self, destination: str) -> None:
        """Honour a navigate effect the way the host now does.

        The host no longer rebuilds Python for a route change. It echoes the new
        route back as an ordinary lifecycle action and lets the app decide what
        that route means.

        Args:
            destination: The route carried by the snapshot's navigate effect.
        """
        self.lifecycle("onRouteChanged", route=destination)

    def _intent_for(
        self, handler: str, bound: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        """Return the intent a control carries in the current snapshot.

        A control is named by its handler, and by the values it binds when
        several controls bind one handler.

        Args:
            handler: The action's function name.
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
        found: list[dict[str, Any]] = []

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                if set(value) == {"fields", "intent"}:
                    named = value["intent"].rpartition(".")[2] == handler
                    if (
                        named
                        and wanted in (None, value["fields"])
                        and value not in found
                    ):
                        found.append(value)
                    return
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(self.snapshot()["root"])
        if len(found) != 1:
            raise AssertionError(f"{len(found)} live intents for {handler} {bound}")
        return found[0]


def titles(snapshot: dict[str, Any]) -> list[str]:
    """Return the note titles a snapshot published.

    Args:
        snapshot: A parsed snapshot.

    Returns:
        The titles, newest first.
    """
    return [note["title"] for note in snapshot["metadata"]["data"]["notes"]]


def data(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return the app data a snapshot published.

    Args:
        snapshot: A parsed snapshot.

    Returns:
        The published data.
    """
    return cast("dict[str, Any]", snapshot["metadata"]["data"])


def effects(snapshot: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Return the effects a snapshot asked the host to run.

    Args:
        snapshot: A parsed snapshot.

    Returns:
        Each effect's kind and payload, in order.
    """
    return [
        (effect["kind"], effect.get("payload", {}))
        for effect in (snapshot.get("metadata") or {}).get("effects", [])
    ]
