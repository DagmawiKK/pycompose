"""Drive an app the way its Android host does, with no device (plan 31 §18.7).

``AppDriver`` starts the app through the same session the device runs, finds
controls in the snapshot it publishes, and acts on them by the intents
the snapshot itself carries, exactly as the renderer does. Navigation effects
are echoed back as the host echoes them, so a test walks the app screen by
screen::

    with AppDriver(Path("examples/notes")) as app:
        app.click(text="New note")
        app.edit("Groceries", id="title")
        assert "Groceries" in app.texts()

``render`` hands the current screen to the JVM renderer for a screenshot and
a semantics dump (``pycompose render``).
"""

from __future__ import annotations

import functools
import json
import os
import subprocess
import sys
import tempfile
import time
import tomllib
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import pycompose
from pycompose.app.session import REFRESH
from pycompose.bridge.imports import fresh_imports
from pycompose.bridge.session import RuntimeSession
from pycompose.extensions.environment import install as install_paths
from pycompose.repository import documents_at
from pycompose.runtime import signal
from pycompose.runtime.loop import LoopThread

Node = dict[str, Any]


class AppDriver:
    """One app session, driven by what its snapshots publish."""

    def __init__(
        self, root: Path, *, route: str = "", restore: str = "", follow: bool = True
    ) -> None:
        """Start the app in ``root`` as its host would.

        Args:
            root: The app root, holding ``pycompose.toml``.
            route: The route the host restored.
            restore: Data the host saved from a previous process.
            follow: Echo navigate effects back as lifecycle actions, as the host does.
        """
        config = tomllib.loads((root / "pycompose.toml").read_text(encoding="utf-8"))
        python = config.get("python", {})
        self.root = root
        self.follow = follow
        # The app's private files live for this session only, so tests never
        # share data and nothing lands in the working directory.
        self._storage = tempfile.TemporaryDirectory(prefix="pycompose-app-")
        files = Path(self._storage.name)
        install_paths(str(files / "files"), str(files / "cache"))
        self._documents = documents_at(files / "files")
        self._documents.__enter__()
        self._imports = fresh_imports(root / python.get("source_dir", "app"))
        self._imports.__enter__()
        # The app runs on a loop thread of its own, as on a device, so the work
        # its view models launch runs between the actions a test delivers.
        self._failures: list[str] = []
        self._refreshes: list[str] = []
        self._effects: list[dict[str, Any]] = []
        self._pulled = ""
        self._loop = LoopThread(self._report)
        signal.install(lambda event, _payload: self._refreshes.append(event))
        started = False
        try:
            self._session = self._loop.call(
                functools.partial(
                    RuntimeSession,
                    python.get("entrypoint", "main:app"),
                    route,
                    debug=True,
                    restore=restore,
                )
            )
            started = True
        finally:
            if not started:
                self._release()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _kind: type[BaseException] | None,
        _error: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """End the session, drop the app's modules and delete its files."""
        self._loop.call(self._session.close)
        self._release()

    def _report(self, scope: str, error: BaseException) -> None:
        self._failures.append(f"{scope}: {error}")

    @property
    def failures(self) -> list[str]:
        """Every launched task that failed, as ``scope: error``.

        Returns:
            The failures, oldest first.
        """
        return list(self._failures)

    @property
    def effects(self) -> list[dict[str, Any]]:
        """Every effect the app asked for, in the snapshots the host pulled.

        Returns:
            The effects, oldest first.
        """
        return list(self._effects)

    def _deliver(self, source: str) -> None:
        """Run one action and pull, then every refresh the app signals."""
        self._loop.call(self._session.accept_action, source)
        self._pull()
        # Let the work the action woke run, then publish what it changed, as
        # the host does when it receives the refresh signal.
        self._loop.call(lambda: None)
        while self._refreshes:
            self._refreshes.clear()
            self._loop.call(self._session.accept_action, envelope(REFRESH, {}))
            self._pull()
            self._loop.call(lambda: None)

    def _pull(self) -> None:
        """Pull as the host does after each pass, keeping the effects it carries."""
        source = self._loop.call(self._session.snapshot)
        if source and source != self._pulled:
            self._pulled = source
            metadata = json.loads(source).get("metadata") or {}
            self._effects.extend(metadata.get("effects", []))

    def _release(self) -> None:
        self._loop.stop()
        signal.install(None)
        self._imports.__exit__(None, None, None)
        self._documents.__exit__(None, None, None)
        install_paths()
        self._storage.cleanup()

    def snapshot(self) -> dict[str, Any]:
        """Return the snapshot the host would render now.

        Returns:
            The parsed snapshot.

        Raises:
            AssertionError: If the app published none; the message is its error.
        """
        source = self._loop.call(self._session.snapshot)
        if not source:
            raise AssertionError(
                self._loop.call(self._session.error) or "the app published no snapshot"
            )
        snapshot: dict[str, Any] = json.loads(source)
        return snapshot

    def nodes(self) -> list[Node]:
        """Every node on screen, parents before children.

        Returns:
            The nodes of the current snapshot.
        """
        found, pending = [], [self.snapshot()["root"]]
        while pending:
            node = pending.pop(0)
            found.append(node)
            pending.extend(node.get("children", []))
        return found

    def texts(self) -> list[str]:
        """Every string a ``text`` or ``label`` prop shows, in screen order.

        Returns:
            The texts.
        """
        return [text for node in self.nodes() for text in sorted(_shown(node))]

    def find(
        self,
        *,
        id: str | None = None,
        text: str | None = None,
        type: str | None = None,
        label: str | None = None,
    ) -> Node:
        """The one node matching every given selector.

        ``id`` matches the end of a node's readable path, so the key a view
        gave it is enough; ``text`` matches the node that shows it; ``label``
        matches the control whose label shows it, as a user names a field.

        Args:
            id: The node's key.
            text: A text it shows.
            type: Its component type.
            label: The text its label shows, as a prop or in its label slot.

        Returns:
            The node.

        Raises:
            AssertionError: Unless exactly one node matches.
        """
        paths = self._loop.call(self._session.node_paths)
        matches = [
            node
            for node in self.nodes()
            if (id is None or _named(paths.get(node["id"], node["id"]), id))
            and (type is None or node["type"] == type)
            and (text is None or text in _shown(node))
            and (label is None or label in _labelled(node))
        ]
        if len(matches) != 1:
            given = {"id": id, "text": text, "type": type, "label": label}
            wanted = {k: v for k, v in given.items() if v}
            raise AssertionError(f"{len(matches)} nodes match {wanted}")
        return matches[0]

    def act(self, prop: str, node: Node, **payload: Any) -> None:
        """Deliver the action a node binds under ``prop``, as the renderer does.

        Args:
            prop: The action prop, such as ``onClick``.
            node: The node.
            **payload: The event's fields.

        Raises:
            AssertionError: If the node binds no action there.
        """
        action = _action(node, prop)
        if action is None:
            raise AssertionError(f"{node['type']} {node['id']} has no {prop}")
        self._deliver(envelope(action, payload))
        self._echo_navigation()

    def click(self, **selector: str) -> None:
        """Click the control a selector names, or the one holding it.

        A button's label is a child of the button: clicking the label clicks
        the nearest enclosing control with an ``onClick``, as a tap does.

        Args:
            **selector: ``id``, ``text`` or ``type``, as :meth:`find` takes them.

        Raises:
            AssertionError: If neither the node nor any parent is clickable.
        """
        node = self.find(**selector)
        parents = {
            child["id"]: n for n in self.nodes() for child in n.get("children", [])
        }
        while _action(node, "onClick") is None:
            if node["id"] not in parents:
                raise AssertionError(f"nothing clickable holds {node['id']}")
            node = parents[node["id"]]
        self.act("onClick", node)

    def edit(self, value: str, **selector: str) -> None:
        """Type ``value`` into the field a selector names, replacing what it holds.

        Args:
            value: The field's new text.
            **selector: ``id``, ``text`` or ``type``, as :meth:`find` takes them.
        """
        node = self.find(**selector)
        props = node.get("props", {})
        if "onEdit" in props:
            # The host's edit report: the text, a caret at its end, and the
            # revision of the value it edited.
            end = len(value)
            revision = props.get("revision", 0)
            self.act(
                "onEdit",
                node,
                text=value,
                selectionStart=end,
                selectionEnd=end,
                revision=revision,
            )
        else:
            self.act("onValueChange", node, value=value)

    def settle(self, timeout: float = 5.0) -> None:
        """Wait until the work the app launched has finished and is on screen.

        Args:
            timeout: Seconds to wait before giving up.
        """
        self.wait_until(self._loop.idle, timeout)

    def wait_until(self, condition: Callable[[], bool], timeout: float = 5.0) -> None:
        """Deliver what launched work publishes until ``condition`` holds.

        Args:
            condition: Checked after each delivery, such as a value on screen.
            timeout: Seconds to wait before giving up.

        Raises:
            AssertionError: If it still does not hold after ``timeout``.
        """
        deadline = time.monotonic() + timeout
        while True:
            # Checked first: work that finished posted its refresh before it
            # finished, so a condition met with no refresh waiting is settled.
            met = condition()
            if self._refreshes:
                self._refreshes.clear()
                self._deliver(envelope(REFRESH, {}))
            elif met:
                return
            elif time.monotonic() > deadline:
                raise AssertionError(f"still waiting after {timeout} s")
            else:
                time.sleep(0.005)

    def lifecycle(self, event: str, **payload: Any) -> None:
        """Deliver a host lifecycle event, such as ``onRouteChanged``.

        Args:
            event: The event's name.
            **payload: Its fields.
        """
        self._deliver(envelope(event, payload))
        self._echo_navigation()

    def render(self, out: Path, name: str = "screen") -> tuple[Path, Path]:
        """Render the current screen on the JVM: a PNG and a semantics dump.

        Args:
            out: Where the files go.
            name: Their base name.

        Returns:
            The PNG and the semantics JSON.

        Raises:
            AssertionError: If rendering failed; the message is its output.
        """
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / f"{name}.json"
            snapshot.write_text(json.dumps(self.snapshot()), encoding="utf-8")
            # The CLI of this very library, whichever is installed elsewhere.
            library = str(Path(pycompose.__file__).resolve().parents[1])
            path = os.pathsep.join(
                filter(None, [library, os.environ.get("PYTHONPATH")])
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pycompose.cli",
                    "render",
                    str(snapshot),
                    "--out",
                    str(out),
                ],
                env={**os.environ, "PYTHONPATH": path},
                cwd=self.root,
                capture_output=True,
                text=True,
                check=False,
            )
        if result.returncode != 0:
            raise AssertionError(result.stderr[-2000:])
        return out / f"{name}.png", out / f"{name}.semantics.json"

    def _echo_navigation(self) -> None:
        if not self.follow:
            return
        effects = (self.snapshot().get("metadata") or {}).get("effects", [])
        for effect in effects:
            if effect.get("kind") == "navigate":
                self.lifecycle("onRouteChanged", **effect.get("payload", {}))


def _named(path: str, key: str) -> bool:
    return path == key or path.rsplit(".", 1)[-1] == key


def _action(node: Node, prop: str) -> object:
    props = node.get("props", {})
    value = props.get(prop)
    if value is None and prop == "onClick":
        # A clickable modifier makes any node tappable, as the renderer applies it.
        operations = (props.get("modifier") or {}).get("operations", [])
        value = next(
            (op.get("onClick") for op in operations if op.get("type") == "clickable"),
            None,
        )
    return value if isinstance(value, str | dict) else None


def envelope(target: object, payload: dict[str, Any]) -> str:
    """Return the envelope a tap on ``target`` sends, as the host builds it.

    Args:
        target: The intent a control carries, or a registry action's name.
        payload: The event's own fields.

    Returns:
        The action envelope as JSON.
    """
    if isinstance(target, dict):
        return json.dumps(
            {"fields": target["fields"], "intent": target["intent"], "payload": payload}
        )
    return json.dumps({"intent": target, "payload": payload})


def _labelled(node: Node) -> set[str]:
    """The label a node shows, as a prop or in its label slot."""
    labels = {
        text
        for child in node.get("children", [])
        if child.get("slot") == "label"
        for text in _shown(child)
    }
    label = node.get("props", {}).get("label")
    if isinstance(label, str):
        labels.add(label)
    return labels


def _shown(node: Node) -> set[str]:
    """The texts a node itself shows."""
    return {
        value
        for key, value in node.get("props", {}).items()
        if key in {"text", "label", "content"} and isinstance(value, str)
    }
