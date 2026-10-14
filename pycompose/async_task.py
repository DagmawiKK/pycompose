"""Work that runs off the worker, and comes back as an ordinary action.

The Python worker is single, and that is not negotiable: it is what makes a
snapshot reproducible and keeps Compose's main thread free of Python. The cost is
that a handler which blocks is a handler that freezes the app::

    @action
    def refresh(state, payload):
        response = httpx.get("https://api.example.com/notes")  # worker stuck
        return screen(...)

``accept_action`` returns immediately, so nothing crashes — but the worker is
gone until the request finishes, and every tap behind it queues silently.

This module is the other half of that problem. Work is handed to a small bounded
executor and the result is **delivered as an action**: the host marshals it to
the main thread, queues it, and the worker runs it through exactly the same path
as a tap. Nothing new crosses the boundary, and unidirectionality is preserved --
the host still only ever sends actions and receives snapshots.

    @action
    def notes_arrived(state: State, payload: NotesArrived) -> State:
        return replace(state, notes=payload["notes"])

    async_task.run(fetch_notes, action=notes_arrived)

The handler is the seam that keeps this typed: the result is checked against the
payload the handler declared, so a network response cannot quietly become app
state of the wrong shape.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pycompose.errors import IrValidationError, StateError
from pycompose.state.app_action import AppAction
from pycompose.utils.json_canonical import canonical_json, check_json

__all__ = ["configure", "last_error", "run", "shutdown"]

#: Threads background work runs on unless the app says otherwise.
#:
#: These are IO-bound, so this is not a CPU count -- it is how many requests an
#: app can have open at once. Android's own default for concurrent connections is
#: around five, and a screen that loads a page plus a couple of thumbnails wants
#: at least that many, so the default is set just above it. An app doing bulk
#: loading should raise it with :func:`configure`.
DEFAULT_WORKERS = 4

#: How much work may be waiting beyond what the threads can take. Beyond this,
#: new work is refused with a diagnostic instead of piling up: a queue that grows
#: without bound holds stale results that all land at once, long after the screen
#: that wanted them is gone.
QUEUE_PER_WORKER = 4

#: Marks a diagnostic that goes stale once the backlog drains.
_BACKLOG = "async work refused"

_workers = DEFAULT_WORKERS
_outstanding = 0
_executor: ThreadPoolExecutor | None = None
_lock = threading.Lock()
_sink: Callable[[str, str], None] | None = None
_error = ""


def configure(*, workers: int = DEFAULT_WORKERS) -> None:
    """Choose how much background work may run at once.

    Call before submitting anything; changing it later discards any work still
    waiting. The default suits a screen loading a handful of things. Raise it for
    bulk loading, lower it on a device where every thread costs something.

    Args:
        workers: Threads to run background work on. Must be at least one.

    Raises:
        StateError: If workers is not a positive integer.
    """
    global _workers, _executor, _outstanding  # noqa: PLW0603 -- read at submit
    if not isinstance(workers, int) or isinstance(workers, bool) or workers < 1:
        raise StateError("workers must be a positive integer")
    with _lock:
        _workers = workers
        pool, _executor, _outstanding = _executor, None, 0
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)


def _pool() -> ThreadPoolExecutor:
    """Return the shared executor, creating it on first use.

    Returns:
        The executor background work runs on.
    """
    global _executor  # noqa: PLW0603 -- one process-wide pool, like the worker
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=_workers,
                thread_name_prefix="PyCompose-async",
            )
        return _executor


def _queue_depth() -> int:
    """Return how much work may wait beyond what the threads can take.

    Returns:
        The queue bound, derived from the worker count.
    """
    return _workers * QUEUE_PER_WORKER


def install_sink(sink: Callable[[str, str], None] | None) -> None:
    """Register where a finished result is delivered.

    The host calls this once the worker is up. Until then, results have nowhere
    to go and are recorded as an error rather than silently dropped.

    Args:
        sink: Receives an action id and its canonical payload text, or None to
            remove the sink.
    """
    global _sink  # noqa: PLW0603 -- installed once per session, read from many
    with _lock:
        _sink = sink


def last_error() -> str:
    """Return the last background failure, for the host to surface.

    Returns:
        A diagnostic, or an empty string when nothing has failed.
    """
    return _error


def _report(message: str) -> None:
    """Record a diagnostic the host will read on its next pull.

    Args:
        message: What went wrong.
    """
    global _error  # noqa: PLW0603 -- guarded by the module lock on write
    with _lock:
        _error = message


def run(
    work: Callable[[], Any],
    action: AppAction[Any, Any],
    *,
    payload: Mapping[str, Any] | None = None,
) -> None:
    """Run ``work`` off the worker and deliver its result to ``action``.

    The call returns immediately; the UI carries on while the work happens. When
    it finishes, the host receives an ordinary action and the worker re-renders.

    Args:
        work: A callable taking no arguments, returning the payload mapping the
            handler declared. It runs on a background thread, so it must not
            touch app state.
        action: The handler the result is delivered to.
        payload: Values bound into the delivered envelope, for work that needs to
            say which request it is answering.

    Raises:
        StateError: If ``work`` is not callable, or ``action`` is not an action.
    """
    if not callable(work):
        raise StateError("async work must be callable")
    if not isinstance(action, AppAction):
        raise StateError("async target must be an app action")
    bound = dict(payload or {})
    try:
        _submit(_pool(), _complete, work, action, bound)
    except QueueFullError as exc:
        _report(
            f"{_BACKLOG}: more than {_queue_depth()} requests are already "
            f"waiting on {_workers} threads"
        )
        raise StateError(str(exc)) from exc
    except RuntimeError as exc:
        # The pool is shut down, which only happens at teardown.
        _report(f"async work rejected: {exc}")


class QueueFullError(RuntimeError):
    """Raised when more work is waiting than the pool is willing to hold."""


def _submit(
    pool: ThreadPoolExecutor,
    work: Callable[..., Any],
    *args: Any,
) -> None:
    """Submit work, refusing rather than letting the queue grow without bound.

    The outstanding count is kept here rather than read out of the executor's own
    queue, which is a private implementation detail that would break on any Python
    upgrade.

    Args:
        pool: The executor to submit to.
        work: The callable to run.
        *args: Arguments for it.

    Raises:
        QueueFullError: If too much work is already outstanding.
        RuntimeError: If the pool has been shut down.
    """
    global _outstanding  # noqa: PLW0603 -- counted under the module lock
    with _lock:
        if _outstanding >= _queue_depth():
            raise QueueFullError("async queue is full")
        _outstanding += 1
    try:
        pool.submit(work, *args)
    except RuntimeError:
        _settle()
        raise


def _settle() -> None:
    """Record that one piece of outstanding work is no longer outstanding.

    When nothing is outstanding the backlog has drained, which is exactly when a
    refusal stops being true. Leaving the message in place would keep a warning on
    screen for the rest of the session.

    Returns:
        Nothing.
    """
    global _outstanding, _error  # noqa: PLW0603 -- counted under the module lock
    with _lock:
        _outstanding = max(0, _outstanding - 1)
        # Only a backlog complaint is out of date now. A request that failed on
        # its own terms stays reported until the app does something about it.
        if _outstanding == 0 and _error.startswith(_BACKLOG):
            _error = ""


def _complete(
    work: Callable[[], Any],
    action: AppAction[Any, Any],
    bound: Mapping[str, Any],
) -> None:
    """Run the work and hand the result to the host.

    Args:
        work: The callable to run off the worker.
        action: The handler the result is delivered to.
        bound: Values bound into the delivered envelope.
    """
    try:
        result = work()
    except Exception as exc:
        _report(f"async work failed: {exc}")
        return
    finally:
        _settle()
    _deliver(result, action, bound)


def _deliver(
    result: object,
    action: AppAction[Any, Any],
    bound: Mapping[str, Any],
) -> None:
    """Hand one finished result to the host.

    Args:
        result: What the work produced.
        action: The handler the result is delivered to.
        bound: Values bound into the delivered envelope.
    """
    try:
        check_json(result)
    except (IrValidationError, TypeError, ValueError) as exc:
        _report(f"async result is not JSON: {exc}")
        return
    merged = {**bound, **(result if isinstance(result, Mapping) else {})}
    try:
        envelope = canonical_json(merged)
    except (IrValidationError, TypeError, ValueError) as exc:
        _report(f"async result is not JSON: {exc}")
        return
    with _lock:
        sink = _sink
    if sink is None:
        _report("async result arrived before the host was listening")
        return
    try:
        sink(action.name, envelope)
    except Exception as exc:
        _report(f"async result not delivered: {exc}")


def shutdown() -> None:
    """Stop accepting work and release the pool's threads.

    The host calls this when a session ends, so a debug reload cannot leave
    threads from the previous build running.
    """
    global _executor, _sink, _error
    with _lock:
        pool, _executor, _sink, _error = _executor, None, None, ""
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)
