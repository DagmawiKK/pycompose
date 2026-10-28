"""One app session on the loop thread: the app module, its back stack and its Store."""

from __future__ import annotations

import functools
import importlib
import logging
import re
import sys
from contextlib import suppress
from pathlib import Path
from threading import current_thread
from types import ModuleType
from typing import Protocol, runtime_checkable

from pycompose.app.app import App
from pycompose.app.session import NavigationSession
from pycompose.bridge.api import BridgeSurface
from pycompose.errors import BridgeError
from pycompose.runtime.loop import LoopThread
from pycompose.state import Store

__all__ = ["RuntimeSession", "compose_once"]

LOGGER = logging.getLogger(__name__)


@runtime_checkable
class _Closeable(Protocol):
    def close(self) -> None: ...


_host_components: frozenset[str] | None = None
"""What the host's handshake said it renders, for every session it starts."""


def offer_components(components: frozenset[str] | None) -> None:
    """Record the components the host's handshake offered.

    Args:
        components: The offered component types, or None when the host listed none.
    """
    global _host_components  # noqa: PLW0603 -- one host per Python process
    _host_components = components


class RuntimeSession:
    """Worker-owned app lifetime, with transactional debug rebuilds.

    The session finds the entry module's ``App`` export and runs it on its back
    stack. It calls the app's container factory exactly once and keeps the
    result across debug reloads, so repositories and other long-lived objects
    live for the session rather than for one import of the app module.
    """

    def __init__(
        self,
        entrypoint: str,
        route: str,
        *,
        debug: bool,
        restore: str = "",
        identity: str = "session",
    ) -> None:
        if (
            re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*", entrypoint)
            is None
        ):
            raise BridgeError("invalid app entrypoint")
        self._module, self._export = entrypoint.split(":")
        self._debug = debug
        self._worker = current_thread()
        self._error = ""
        self._container: object | None = None
        self._navigation: NavigationSession | None = None
        self.identity = identity
        self._surface = self._build(route, restore)

    def _require_worker(self) -> None:
        if current_thread() is not self._worker:
            raise BridgeError("runtime calls must run on the owning worker")

    def _resolve_container(self, app: App) -> object | None:
        """Adopt the entry object's container factory once, then retain it.

        Args:
            app: The entry object this build discovered.

        Returns:
            The session container, or None when the app declares none.
        """
        if self._container is not None:
            return self._container
        if app.container is None:
            return None
        self._container = app.container()
        return self._container

    def _build(self, route: str, restore: str = "") -> BridgeSurface:
        module = importlib.import_module(self._module)
        app = getattr(module, self._export, None)
        self._navigation = None
        if not isinstance(app, App):
            raise BridgeError(
                "entrypoint must name the module's pycompose.app.App export",
                entrypoint=f"{self._module}:{self._export}",
            )
        return self._build_view(app, route, restore)

    def _build_view(self, app: App, route: str, restore: str) -> BridgeSurface:
        """Start the app on its start destination, or its restored stack.

        Args:
            app: The app.
            route: The route the host restored or was opened with.
            restore: Saved state the host handed back, or empty.

        Returns:
            The surface serving the destination's view model.

        Raises:
            BridgeError: If the first snapshot is invalid.
        """
        screen = NavigationSession(
            app, self._resolve_container(app), route, restore, report=self._report_task
        )
        built = False
        try:
            surface = BridgeSurface(
                Store(screen.snapshot_state(None)),
                screen,
                debug=self._debug,
                host_components=_host_components,
            )
            if surface.expose_latest_snapshot() is None:
                raise BridgeError("app build produced no valid snapshot")
            built = True
        finally:
            if not built:
                # Its view models must not keep working behind a failed build.
                screen.close()
        self._navigation = screen
        return surface

    def _report_task(self, scope: str, error: BaseException) -> None:
        self._error = f"{scope}: {error}"
        LOGGER.warning("Task in %s failed: %s", scope, error, exc_info=error)

    def accept_action(self, source: str) -> None:
        """Validate and run one native action before the host pulls a snapshot.

        Args:
            source: Data-only action JSON envelope.
        """
        self._require_worker()
        self._surface.accept_action(source)

    def snapshot(self) -> str:
        """Return the last valid canonical snapshot as data.

        Returns:
            JSON for the latest worker-owned snapshot.
        """
        self._require_worker()
        return self._surface.expose_latest_snapshot() or ""

    def envelope(self, surface: str, base_serial: int) -> str:
        """Return the latest snapshot as a patch against the host's base, or whole.

        Args:
            surface: The surface being pulled.
            base_serial: The serial of the snapshot the host holds; -1 for none.

        Returns:
            The envelope JSON, or empty before any valid snapshot.
        """
        self._require_worker()
        return self._surface.expose_envelope(base_serial, surface)

    def window(self, surface: str, key: str, first: int, last: int) -> None:
        """Compose the window of a lazy container the host now shows.

        Args:
            surface: The surface showing the container.
            key: The container's window key.
            first: The first item index wanted.
            last: The last item index wanted.
        """
        self._require_worker()
        self._surface.request_window(key, first, last, surface)

    def error(self) -> str:
        """Return a debug diagnostic without leaking Python exceptions or objects.

        Returns:
            Error text, or an empty string when no diagnostic is available.
        """
        self._require_worker()
        return self._error or self._surface.expose_latest_error()

    def node_paths(self) -> dict[str, str]:
        """Return each node name's readable path, kept only in debug.

        Returns:
            Readable path by node id; empty in release.
        """
        self._require_worker()
        return self._surface.node_paths()

    def last_pass(self) -> str:
        """Return the last action pass's time by phase.

        Returns:
            JSON milliseconds by phase.
        """
        self._require_worker()
        return self._surface.expose_last_pass()

    def reload(self, route: str, restore: str = "") -> bool:
        """Re-import app modules and build on this worker, retaining last-good IR.

        Only modules beside the app entrypoint are evicted, never the runtime.
        This hook does not download source files; dev delivery invokes it after
        updated source has been staged on the device. The app is rebuilt from
        its live back stack, its container kept; the old view models are
        cleared only once the new ones are built, so a failed reload changes
        nothing.

        Args:
            route: The route to open when no stack is live yet.
            restore: Saved state to restore when no stack is live yet.

        Returns:
            Whether a new valid app session replaced the previous one.
        """
        self._require_worker()
        if not self._debug:
            return False
        entry = sys.modules[self._module]
        filename = getattr(entry, "__file__", None)
        if not filename:
            self._error = "app module has no reloadable source"
            return False
        top = sys.modules[self._module.split(".")[0]]
        directory = Path(getattr(top, "__file__", None) or filename).parent
        if "." in self._module:
            directory = directory.parent
        previous = _user_modules(directory)
        previous_navigation = self._navigation
        if previous_navigation is not None:
            # The live stack is newer than anything the host saved: every view
            # model is rebuilt from it with the new code.
            route, restore = previous_navigation.top_key, previous_navigation.saved()
        for name, module in previous.items():
            del sys.modules[name]
            cached = getattr(module, "__cached__", None)
            if cached:
                # APK-bundled modules may have read-only bytecode.
                with suppress(OSError):
                    Path(cached).unlink(missing_ok=True)
        importlib.invalidate_caches()
        try:
            candidate = self._build(route, restore)
        except Exception as exc:
            for name in _user_modules(directory):
                del sys.modules[name]
            sys.modules.update(previous)
            self._navigation = previous_navigation
            self._error = str(exc)
            return False
        else:
            self._surface.close()
            self._surface = candidate
            self._error = ""
            return True

    def close(self) -> None:
        """Retire registered work and close its resources off the Compose thread.

        A container that has a ``close`` method is closed with the session, as the
        app's long-lived objects end with the process on a device.
        """
        self._require_worker()
        self._surface.close()
        if isinstance(self._container, _Closeable):
            self._container.close()


def _user_modules(directory: Path) -> dict[str, ModuleType]:
    result = {}
    for name, module in tuple(sys.modules.items()):
        path = getattr(module, "__file__", None)
        if (
            name == "pycompose"
            or name.startswith("pycompose.")
            or not isinstance(path, str)
        ):
            continue
        if Path(path).is_relative_to(directory):
            result[name] = module
    return result


def compose_once(entrypoint: str) -> tuple[str, str]:
    """Start the app on a loop thread of its own, as a device does, then end it.

    Args:
        entrypoint: The app's ``module:export``.

    Returns:
        The first snapshot, or empty when none was valid, and the error.
    """

    def report(scope: str, error: BaseException) -> None:
        LOGGER.warning("Task in %s failed: %s", scope, error, exc_info=error)

    loop = LoopThread(report, name="pycompose-compose-once")
    try:
        session = loop.call(
            functools.partial(RuntimeSession, entrypoint, "", debug=True)
        )
        try:
            return loop.call(session.snapshot), loop.call(session.error)
        finally:
            loop.call(session.close)
    finally:
        loop.stop()
