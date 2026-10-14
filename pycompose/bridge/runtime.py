"""Device entrypoint: Python owns app modules, handlers, Store and composition."""

from __future__ import annotations

import importlib
import inspect
import re
import sys
from contextlib import suppress
from pathlib import Path
from threading import current_thread
from types import ModuleType

from pycompose.bridge.api import BridgeSurface
from pycompose.errors import BridgeError
from pycompose.state import Actions, State, Store
from pycompose.state.app_action import AppAction


class RuntimeSession:
    """Worker-owned app lifetime, with transactional debug rebuilds.

    The session is the app's container owner: it resolves the app's declared
    ``container`` factory exactly once and hands the resulting object to every
    subsequent ``build``, including after a debug reload. Repositories and
    other long-lived objects therefore live for the session rather than for one
    import of the app module.
    """

    def __init__(
        self, entrypoint: str, route: str, *, debug: bool, restore: str = ""
    ) -> None:
        if (
            re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*", entrypoint)
            is None
        ):
            raise BridgeError("invalid app entrypoint")
        self._module, self._function = entrypoint.split(":")
        self._debug = debug
        self._worker = current_thread()
        self._error = ""
        self._container: object | None = None
        self._surface = self._build(route, restore)

    def _require_worker(self) -> None:
        if current_thread() is not self._worker:
            raise BridgeError("runtime calls must run on the owning worker")

    def _resolve_container(self, module: ModuleType) -> object | None:
        """Adopt the app's declared container once, then retain it.

        Args:
            module: Freshly imported app module for this build.

        Returns:
            The session container, or None when the app declares none.

        Raises:
            BridgeError: If the app declares a container that is not callable.
        """
        if self._container is not None:
            return self._container
        factory = getattr(module, "container", None)
        if factory is None:
            return None
        if not callable(factory):
            raise BridgeError("app container must be a zero-argument callable")
        self._container = factory()
        return self._container

    def _build(self, route: str, restore: str = "") -> BridgeSurface:
        module = importlib.import_module(self._module)
        build = getattr(module, self._function)
        signature = inspect.signature(build)
        container = self._resolve_container(module)
        arguments: dict[str, object] = {}
        if "route" in signature.parameters:
            arguments["route"] = route
        if "container" in signature.parameters:
            arguments["container"] = container
        if "restore" in signature.parameters and restore:
            # Only ever the host's own saved bytes, handed straight back.
            arguments["restore"] = restore
        state = build(**arguments)
        if not isinstance(state, State):
            raise BridgeError("app build must return State")
        definitions = [
            value for value in vars(module).values() if isinstance(value, AppAction)
        ]
        actions = getattr(module, "actions", None)
        if actions is None:
            actions = Actions(*definitions)
        if not isinstance(actions, Actions):
            raise BridgeError("app actions must be an Actions instance")
        surface = BridgeSurface(Store(state), actions, debug=self._debug)
        if surface.expose_latest_snapshot() is None:
            raise BridgeError("app build produced no valid snapshot")
        return surface

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

    def error(self) -> str:
        """Return a debug diagnostic without leaking Python exceptions or objects.

        Returns:
            Error text, or an empty string when no diagnostic is available.
        """
        self._require_worker()
        return self._error or self._surface.expose_latest_error()

    def reload(self, route: str, restore: str = "") -> None:
        """Re-import app modules and build on this worker, retaining last-good IR.

        Only modules beside the app entrypoint are evicted, never the runtime.
        This hook does not download source files; dev delivery invokes it after
        updated source has been staged on the device.

        Args:
            route: Minimal route to supply when rebuilding the app.
            restore: Saved app data to hand back to the rebuilt app.
        """
        self._require_worker()
        if not self._debug:
            return
        entry = sys.modules[self._module]
        filename = getattr(entry, "__file__", None)
        if not filename:
            self._error = "app module has no reloadable source"
            return
        top = sys.modules[self._module.split(".")[0]]
        directory = Path(getattr(top, "__file__", None) or filename).parent
        if "." in self._module:
            directory = directory.parent
        previous = _user_modules(directory)
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
            self._error = str(exc)
        else:
            self._surface = candidate
            self._error = ""


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


def start(entrypoint: str, route: str, debug: bool, restore: str = "") -> None:
    """Create the app session on the host's single worker.

    Args:
        entrypoint: Module:function app entrypoint.
        route: Restored minimal navigation state.
        debug: Enable debug-only reload and detailed diagnostics.
        restore: Saved app data handed back for ``build`` to rehydrate from.
    """
    global _session  # noqa: PLW0603 -- one worker-owned session per Python process
    _session = RuntimeSession(entrypoint, route, debug=debug, restore=restore)


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


def fetch_latest_error() -> str:
    """Pull data-only debug diagnostics.

    Returns:
        Diagnostic text or an empty string.
    """
    return _session.error() if _session is not None else ""


def reload(route: str, restore: str = "") -> None:
    """Invoke the debug rebuild hook on the Python worker.

    Args:
        route: Current minimal route.
        restore: Saved app data to hand back to the rebuilt app.
    """
    if _session is not None:
        _session.reload(route, restore)
