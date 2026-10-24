"""Device entrypoint: Python owns app modules, handlers, Store and composition."""

from __future__ import annotations

import importlib
import re
import sys
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from threading import current_thread
from types import ModuleType
from typing import Any, cast
from uuid import uuid4

from pycompose import async_task
from pycompose.bridge.api import BridgeSurface
from pycompose.bridge.handshake import answer, offered_components
from pycompose.core.context import AppContext, carried, context
from pycompose.core.context import install as install_context
from pycompose.errors import BridgeError
from pycompose.extensions.environment import install as install_paths
from pycompose.state import Actions, App, Store, actions_for_module


class RuntimeSession:
    """Worker-owned app lifetime, with transactional debug rebuilds.

    The session finds the entry module's ``App`` export and runs it: the app
    owns the shell, the view and the container factory, and the session calls
    that factory exactly once, retaining the result across debug reloads.
    Repositories and other long-lived objects therefore live for the session
    rather than for one import of the app module.
    """

    def __init__(
        self, entrypoint: str, route: str, *, debug: bool, restore: str = ""
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
        self.identity = uuid4().hex
        self._surface = self._build(route, restore)

    def _require_worker(self) -> None:
        if current_thread() is not self._worker:
            raise BridgeError("runtime calls must run on the owning worker")

    def _resolve_container(self, app: App[Any]) -> object | None:
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
        if not isinstance(app, App):
            raise BridgeError(
                "entrypoint must name the module's App export",
                entrypoint=f"{self._module}:{self._export}",
            )
        container = self._resolve_container(app)
        actions, problem = actions_for_module(module, app.session_view)
        if problem is not None:
            raise BridgeError(problem)
        # Before `app.build`, because a composable reached during the first
        # render resolves its registry from this. The module is already
        # imported, so both halves of the context exist by now.
        # The context carries the registry plus whatever the app's own container
        # holds, so a render function reaches a use case the same way Compose
        # reaches anything else: by name, from the ambient.
        install_context(
            AppContext(
                actions=actions,
                container=container,
                **carried(container),
            )
        )
        self._check_injection(actions, container)
        actions.install_container(container)
        state = app.build(route=route, restore=restore)
        surface = BridgeSurface(
            Store(state),
            actions,
            debug=self._debug,
            host_components=_host_components,
        )
        if surface.expose_latest_snapshot() is None:
            raise BridgeError("app build produced no valid snapshot")
        return surface

    def _check_injection(self, actions: Actions, container: object | None) -> None:
        """Fail at startup when an action wants a container the app never declared.

        Every handler's signature is known before the first frame is drawn, so
        this is the whole of the check a compiler would do for a framework: a
        missing binding is reported now, with the id of the action that asked,
        rather than as an ``AttributeError`` on whichever control a user happens
        to tap first.

        Args:
            actions: The app's registry, freshly built or reloaded.
            container: The session container, or None when none was declared.

        Raises:
            BridgeError: If any action declares an injected parameter and no
                container was declared.
        """
        wanted = actions.injected
        if wanted and container is None:
            raise BridgeError(
                "app actions ask for a container but the entrypoint declares none",
                injects=",".join(wanted),
            )

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

    def reload(self, route: str, restore: str = "") -> bool:
        """Re-import app modules and build on this worker, retaining last-good IR.

        Only modules beside the app entrypoint are evicted, never the runtime.
        This hook does not download source files; dev delivery invokes it after
        updated source has been staged on the device.

        Args:
            route: Minimal route to supply when rebuilding the app.
            restore: Saved app data to hand back to the rebuilt app.

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
        previous_context = context()
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
            install_context(previous_context)
            self._error = str(exc)
            return False
        else:
            self._surface.close(successor=candidate)
            self._surface = candidate
            self._error = ""
            return True

    def close(self) -> None:
        """Retire registered work and close its resources off the Compose thread."""
        self._require_worker()
        self._surface.close()


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


_session: RuntimeSession | None = None
_host_components: frozenset[str] | None = None
"""What the host's handshake said it renders, for every session it starts."""


def handshake(offer: str) -> str:
    """Answer the host's handshake before any session starts.

    Args:
        offer: The host's protocol and offered capabilities, as JSON.

    Returns:
        This side's protocol and offered capabilities, as JSON.
    """
    global _host_components  # noqa: PLW0603 -- one host per Python process
    reply = answer(offer)
    _host_components = offered_components(offer)
    return reply


def start(
    entrypoint: str,
    route: str,
    debug: bool,
    restore: str = "",
    files_dir: str = "",
    cache_dir: str = "",
) -> str:
    """Create the app session on the host's single worker.

    Args:
        entrypoint: Module:function app entrypoint.
        route: Restored minimal navigation state.
        debug: Enable debug-only reload and detailed diagnostics.
        restore: Saved app data handed back for ``build`` to rehydrate from.
        files_dir: Private persistent path supplied as a host string.
        cache_dir: Evictable private path supplied as a host string.

    Returns:
        A data-only session identity used to reject obsolete host teardown.
    """
    global _session  # noqa: PLW0603 -- one worker-owned session per Python process
    if _session is not None:
        _session.close()
    install_paths(files_dir, cache_dir)
    _session = RuntimeSession(entrypoint, route, debug=debug, restore=restore)
    return _session.identity


def close(identity: str = "") -> None:
    """Retire an app on its worker without closing a replacement host's session.

    Args:
        identity: Host's session identity, or empty for explicit current-session close.
    """
    global _session  # noqa: PLW0603 -- host owns session start/close
    if identity and (_session is None or _session.identity != identity):
        return
    if _session is not None:
        _session.close()
        _session = None
    async_task.shutdown()
    install_paths()
    install_context(None)


def install_async_sink(sink: object, admission: object = None) -> None:
    """Register where background results are delivered on this worker.

    Args:
        sink: A callable taking an action id and its canonical payload text, or
            None to stop delivering.
        admission: Optional thread-safe native queue admission returning a boolean.
    """
    async_task.install_sink(
        cast("Callable[[str, str], None]", sink),
        admission=cast("Callable[[str, str], bool] | None", admission),
    )


def accept_action(source: str) -> None:
    """Forward one data-only action to the Python-owned session.

    Args:
        source: JSON action envelope.

    Raises:
        BridgeError: If the host has not initialized the app session.
    """
    if _session is None:
        raise BridgeError("app session not started")
    _session.accept_action(source)


def fetch_latest_snapshot() -> str:
    """Pull canonical JSON from the worker-owned app session.

    Returns:
        Snapshot JSON, or an empty string before initialization.
    """
    return _session.snapshot() if _session is not None else ""


def fetch_latest(surface: str, base_serial: int) -> str:
    """Pull the latest snapshot as a patch against the host's base, or whole.

    Args:
        surface: The surface being pulled.
        base_serial: The serial of the snapshot the host holds; -1 for none.

    Returns:
        The envelope JSON, or an empty string before initialization.
    """
    return _session.envelope(surface, base_serial) if _session is not None else ""


def request_window(surface: str, key: str, first: int, last: int) -> None:
    """Ask the session to compose a window of one lazy container.

    Args:
        surface: The surface showing the container.
        key: The container's window key.
        first: The first item index wanted.
        last: The last item index wanted.

    Raises:
        BridgeError: If the host has not initialized the app session.
    """
    if _session is None:
        raise BridgeError("app session not started")
    _session.window(surface, key, first, last)


def fetch_latest_error() -> str:
    """Pull data-only debug diagnostics.

    Background work records its failures here too, so one surface shows the app
    everything that has gone wrong rather than only what went wrong on the
    worker.

    Returns:
        Diagnostic text or an empty string.
    """
    parts = [
        _session.error() if _session is not None else "",
        async_task.last_error(),
    ]
    return " / ".join(part for part in parts if part)


def reload(route: str, restore: str = "") -> bool:
    """Invoke the debug rebuild hook on the Python worker.

    Args:
        route: Current minimal route.
        restore: Saved app data to hand back to the rebuilt app.

    Returns:
        Whether the debug rebuild replaced the app session.
    """
    if _session is not None:
        return _session.reload(route, restore)
    return False
