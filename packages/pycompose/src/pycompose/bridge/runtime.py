"""Device entrypoint: Python owns app modules, handlers, Store and composition."""

from __future__ import annotations

import functools
import json
import logging
import sys
from collections.abc import Callable
from typing import ParamSpec, TypeVar, cast

from pycompose.bridge.handshake import answer, offered_components
from pycompose.bridge.inputs import InputLog, digest
from pycompose.bridge.session import RuntimeSession, offer_components
from pycompose.errors import BridgeError
from pycompose.runtime import signal
from pycompose.runtime.loop import LoopThread
from pycompose.storage.paths import install as install_paths

LOGGER = logging.getLogger(__name__)
P = ParamSpec("P")
T = TypeVar("T")

_loop: LoopThread | None = None
"""The process's loop thread: every call that touches session state runs on it."""
_failure = ""
"""The latest supervised failure on the loop, for the host's diagnostics."""


def _report(scope: str, error: BaseException) -> None:
    global _failure  # noqa: PLW0603 -- written only on the loop thread
    _failure = f"{scope}: {error}"
    LOGGER.warning("Task in %s failed: %s", scope, error, exc_info=error)


def _loop_thread() -> LoopThread:
    global _loop  # noqa: PLW0603 -- one loop thread per Python process
    if _loop is None:
        _loop = LoopThread(_report)
    return _loop


def _on_loop(work: Callable[P, T]) -> Callable[P, T]:
    """Run ``work`` on the loop thread, whichever thread the host calls from."""

    @functools.wraps(work)
    def run(*args: P.args, **kwargs: P.kwargs) -> T:
        return _loop_thread().call(functools.partial(work, *args, **kwargs))

    return run


_log: InputLog | None = None
"""The debug session's input log, or None when not recording."""

RECORDED = frozenset({"start", "close", "accept_action", "request_window", "reload"})
"""The calls that change what a session shows; the rest only read it."""


def _recorded(work: Callable[P, T]) -> Callable[P, T]:
    """Record ``work``'s call and the snapshot it leaves, while a log is open."""

    @functools.wraps(work)
    def run(*args: P.args, **kwargs: P.kwargs) -> T:
        result = work(*args, **kwargs)
        if _log is not None:
            snapshot = _session.snapshot() if _session is not None else ""
            _log.add(work.__name__, tuple(args), dict(kwargs), snapshot)
        return result

    return run


@_on_loop
def fetch_input_log() -> str:
    """Return the debug session's inputs as JSON lines, for replay.

    Returns:
        The log, or an empty string when the session is not recording.
    """
    return _log.dumps() if _log is not None else ""


def replay(text: str) -> int | None:
    """Re-run a recorded input log and check each snapshot against the record.

    Args:
        text: A log returned by :func:`fetch_input_log`.

    Returns:
        The index of the first input whose snapshot differs, or None when
        every snapshot matches.
    """
    calls = {name: globals()[name] for name in RECORDED}
    for index, entry in enumerate(InputLog.loads(text)):
        calls[entry.call](*entry.args, **entry.kwargs)
        if digest(fetch_latest_snapshot()) != entry.snapshot:
            return index
    return None


def heartbeat() -> float:
    """Return seconds since the loop thread last proved it was running.

    Returns:
        A small number while the loop runs; a growing one if it is stuck.
    """
    return _loop_thread().since_heartbeat()


_session: RuntimeSession | None = None


def handshake(offer: str) -> str:
    """Answer the host's handshake before any session starts.

    Args:
        offer: The host's protocol and offered capabilities, as JSON.

    Returns:
        This side's protocol and offered capabilities, as JSON.
    """
    reply = answer(offer)
    offer_components(offered_components(offer))
    return reply


def use_source(path: str) -> None:
    """Import the app from ``path`` first: a dev client's bundle (plan 31 §18.8).

    Args:
        path: The app's Python directory, as the dev server served it.
    """
    if path not in sys.path:
        sys.path.insert(0, path)


@_on_loop
@_recorded
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
    global _session, _log  # noqa: PLW0603 -- one worker-owned session per Python process
    _log = InputLog() if debug else None
    if _session is not None:
        _session.close()
    install_paths(files_dir, cache_dir)
    # The host compares this to reject a teardown aimed at an older session.
    identity = f"{_loop_thread().scheduler.random().getrandbits(64):016x}"
    _session = RuntimeSession(
        entrypoint, route, debug=debug, restore=restore, identity=identity
    )
    return _session.identity


@_on_loop
@_recorded
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
    signal.install(None)
    install_paths()


def install_async_sink(sink: object, admission: object = None) -> None:
    """Register where the app's refresh signal goes.

    Args:
        sink: A callable taking an event id and its JSON payload, or None to
            stop sending.
        admission: Optional thread-safe native queue admission returning a boolean.
    """
    signal.install(
        cast("Callable[[str, str], None] | None", sink),
        cast("Callable[[str, str], bool] | None", admission),
    )


@_on_loop
@_recorded
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


@_on_loop
def fetch_latest_snapshot() -> str:
    """Pull canonical JSON from the worker-owned app session.

    Returns:
        Snapshot JSON, or an empty string before initialization.
    """
    return _session.snapshot() if _session is not None else ""


@_on_loop
def fetch_latest(surface: str, base_serial: int) -> str:
    """Pull the latest snapshot as a patch against the host's base, or whole.

    Args:
        surface: The surface being pulled.
        base_serial: The serial of the snapshot the host holds; -1 for none.

    Returns:
        The envelope JSON, or an empty string before initialization.
    """
    return _session.envelope(surface, base_serial) if _session is not None else ""


@_on_loop
@_recorded
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


@_on_loop
def fetch_latest_error() -> str:
    """Pull data-only debug diagnostics.

    Launched work records its failures here too, so one surface shows
    everything that has gone wrong rather than only what went wrong in an
    action.

    Returns:
        Diagnostic text or an empty string.
    """
    parts = [
        _session.error() if _session is not None else "",
        _failure,
    ]
    return " / ".join(part for part in parts if part)


@_on_loop
def fetch_counters() -> str:
    """Pull release-safe counters: passes, publications, failures, phase time.

    Returns:
        JSON counters, with the seconds since the loop last ran; an object
        holding only that before a session starts.
    """
    counters = _session.counters() if _session is not None else {}
    return json.dumps({**counters, "loopIdleSeconds": round(heartbeat(), 3)})


@_on_loop
def fetch_node_paths() -> str:
    """Pull each node name's readable path, for debug diagnostics.

    Returns:
        JSON readable path by node id; an empty object in release.
    """
    return json.dumps(_session.node_paths() if _session is not None else {})


@_on_loop
def fetch_last_pass() -> str:
    """Pull the last action pass's time by phase, for the host's pass log.

    Returns:
        JSON milliseconds by phase, or an empty object before a session.
    """
    return _session.last_pass() if _session is not None else "{}"


@_on_loop
@_recorded
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
