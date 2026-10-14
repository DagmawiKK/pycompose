"""Drive the Notes app the way the Android host does, without a device.

Every action id is read out of the snapshot's own bindings rather than guessed,
which is exactly what the renderer does.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(ROOT))

from pycompose.bridge import BridgeSurface  # noqa: E402
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
        self._bridge = BridgeSurface(
            Store(entrypoint.build(route=route, restore=restore)), entrypoint.actions
        )

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

    def tap(self, handler: str, instance: str = "", **payload: Any) -> None:
        """Deliver one action envelope addressed by handler and instance.

        Args:
            handler: The action's function name.
            instance: The bind instance that names this control.
            **payload: Event fields the handler declares.
        """
        action_id = self._id_for(handler, instance)
        self._bridge.accept_action(
            json.dumps({"actionId": action_id, "payload": payload})
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

    def _id_for(self, handler: str, instance: str) -> str:
        """Return the binding id a control was given in the current snapshot.

        Args:
            handler: The action's function name.
            instance: The bind instance for this control.

        Returns:
            The binding id.

        Raises:
            AssertionError: If no live binding matches.
        """
        bindings = (self.snapshot().get("metadata") or {}).get("actionBindings", {})
        for binding_id in bindings:
            if binding_id.endswith(f".{handler}.{instance}"):
                return cast("str", binding_id)
        raise AssertionError(
            f"no live binding for {handler}.{instance}: {list(bindings)}"
        )


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
