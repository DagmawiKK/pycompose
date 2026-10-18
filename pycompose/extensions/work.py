"""Bounded resource execution with explicit ownership and physical retirement."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Generic, Literal, TypeVar, cast

from pycompose.errors import StateError
from pycompose.extensions.delivery import Dispatcher, Ticket, current
from pycompose.state.app_action import AppAction

T = TypeVar("T")
R = TypeVar("R")
_UNOPENED = object()
Policy = Literal["independent", "latest", "single_flight"]


def _validate(
    operation: Callable[..., Any],
    targets: tuple[AppAction[Any, Any] | None, ...],
    key: str | None,
    policy: Policy,
) -> None:
    if not callable(operation):
        raise StateError("resource operation must be callable")
    if policy not in {"independent", "latest", "single_flight"}:
        raise StateError("unknown extension task policy")
    if key is not None and (not isinstance(key, str) or not key):
        raise StateError("extension task key must be a nonempty string")
    if policy != "independent" and key is None:
        raise StateError("key is required for this extension task policy")
    if any(
        target is not None and not isinstance(target, AppAction) for target in targets
    ):
        raise StateError("extension target must be a declared action")
    if any(target is not None for target in targets) and current() is None:
        raise StateError("action outcomes must be submitted from a worker action")


class Task(Generic[R]):
    """Logical interest in work, distinct from the physical Python operation."""

    def __init__(self, owner: Resource[Any]) -> None:
        self._owner = owner
        self._future: Future[R] = Future()
        self._finished = False
        self._cancelled = False
        self._delivery: Ticket | None = None

    def cancel(self) -> None:
        """Discard interest and cancel queued work, never forcibly stop a thread."""
        with self._owner._lock:
            self._cancelled = True
            if self._delivery is not None:
                self._delivery.cancel()
            self._future.cancel()

    @property
    def diagnostic(self) -> str:
        """Return a safe outcome diagnostic, without library exception content.

        Returns:
            A category string or empty text.
        """
        return self._delivery.diagnostic if self._delivery is not None else ""

    def result(self, timeout: float | None = None) -> R:
        """Wait for the physical operation; never call this on the app worker.

        Args:
            timeout: Maximum wait in seconds, or no deadline.

        Returns:
            The library's original Python result, including logically obsolete work.

        Raises:
            StateError: If this is an app action.
        """
        if current() is not None:
            raise StateError("cannot wait for extension work on the state worker")
        return self._future.result(timeout)

    def _reusable(self, dispatcher: Dispatcher | None) -> bool:
        delivery = self._delivery
        return (
            not self._finished
            and not self._cancelled
            and (
                delivery is None
                or (delivery.dispatcher is dispatcher and delivery.pending)
            )
        )


class Resource(Generic[T]):
    """A lazily opened library object and the execution lane that owns it.

    A single worker preserves thread affinity. Multiple workers are an explicit
    assertion by the integration that concurrent use of its object is safe.
    No library is imported, recognized or special-cased here.
    """

    def __init__(
        self,
        factory: Callable[[], T],
        *,
        close: Callable[[T], None],
        workers: int = 1,
        capacity: int = 16,
    ) -> None:
        """Declare ownership without opening the resource or starting threads.

        Args:
            factory: Opens the object on its execution lane on first use.
            close: Disposes that object after all physical operations retire.
            workers: Concurrent users; one for thread-affine connections.
            capacity: Maximum admitted operations, including running obsolete work.

        Raises:
            StateError: If callables or positive integer bounds are invalid.
        """
        if not callable(factory) or not callable(close):
            raise StateError("resource factory and close must be callable")
        if any(type(v) is not int or v < 1 for v in (workers, capacity)):
            raise StateError("workers and capacity must be positive integers")
        self._factory, self._dispose = factory, close
        self._workers, self._capacity = workers, capacity
        self._lock = threading.RLock()
        self._opening = threading.Lock()
        self._value: T | object = _UNOPENED
        self._pool: ThreadPoolExecutor | None = None
        self._tasks: set[Task[Any]] = set()
        self._physical = 0
        self._closed = False
        self._cleanup: Future[None] = Future()
        self._cleanup_started = False
        self._keys: dict[str, Task[Any]] = {}
        self._owners: set[Dispatcher] = set()

    def submit(
        self,
        operation: Callable[[T], R],
        *,
        success: AppAction[Any, Any] | None = None,
        failure: AppAction[Any, Any] | None = None,
        encode: Callable[[R], Mapping[str, object]] | None = None,
        error: Callable[[Exception], Mapping[str, object]] | None = None,
        key: str | None = None,
        policy: Policy = "independent",
    ) -> Task[R]:
        """Run a normal library operation without blocking the caller.

        Args:
            operation: Uses the resource on its owning execution lane.
            success: Declared success action, registered from a worker transition.
            failure: Declared failure action; default payload is a safe error type.
            encode: Maps a rich Python result to the success action's named fields.
            error: Explicit exception-to-failure payload mapper.
            key: Owner-local request identity for deduplication or supersession.
            policy: Independent, latest-result-wins, or concurrent single-flight.

        Returns:
            A handle distinguishing logical cancellation from physical completion.

        Raises:
            StateError: If the resource is closed, saturated or work is not callable.
        """
        _validate(operation, (success, failure), key, policy)
        dispatcher = current()
        with self._lock:
            if self._closed:
                raise StateError("resource is closed")
            previous = self._keys.get(key) if key is not None else None
            if (
                previous is not None
                and policy == "single_flight"
                and previous._reusable(dispatcher)
            ):
                return cast("Task[R]", previous)
            if previous is not None and policy == "latest":
                previous.cancel()
            if len(self._tasks) >= self._capacity:
                raise StateError("resource queue is full")
            if self._pool is None:
                self._pool = ThreadPoolExecutor(
                    max_workers=self._workers, thread_name_prefix="PyCompose-extension"
                )
            task: Task[R] = Task(self)
            if dispatcher is not None:
                self._attach(dispatcher)
                if success is not None or failure is not None:
                    task._delivery = Ticket(
                        dispatcher,
                        lambda: self._release(task),
                        success,
                        failure,
                        encode,
                        error,
                    )
                    dispatcher.register(task._delivery)
            self._tasks.add(task)
            if key is not None:
                self._keys[key] = task
            self._physical += 1
            self._pool.submit(self._invoke, task, operation)
            return task

    def _invoke(self, task: Task[R], operation: Callable[[T], R]) -> None:
        # A cancelled Future must not remove executor work-item accounting before
        # its closure is physically dequeued. Only this wrapper retires the slot.
        with self._lock:
            pass
        try:
            if not task._future.set_running_or_notify_cancel():
                return
            with self._opening:
                if self._value is _UNOPENED:
                    self._value = self._factory()
            result = operation(cast("T", self._value))
        except BaseException as exc:
            if task._delivery is not None:
                if isinstance(exc, Exception):
                    task._delivery.complete(None, exc)
                else:
                    task._delivery.cancel()
            self._finish(task)
            task._future.set_exception(exc)
        else:
            if task._delivery is not None:
                task._delivery.complete(result)
            self._finish(task)
            task._future.set_result(result)
        finally:
            self._finish(task)

    def _finish(self, task: Task[Any]) -> None:
        with self._lock:
            if task._finished:
                return
            task._finished = True
            self._physical -= 1
            self._release(task)
            self._maybe_close()

    def _attach(self, owner: Dispatcher) -> None:
        with owner.lock:
            if owner.closed:
                raise StateError("extension session is closed")
            owner.resources.add(self)
            self._owners.add(owner)

    def _transfer(self, previous: Dispatcher, successor: Dispatcher | None) -> None:
        with self._lock:
            self._owners.discard(previous)
            if successor is not None and not self._closed:
                self._attach(successor)
            elif successor is None:
                self.close()

    def _release(self, task: Task[Any]) -> None:
        with self._lock:
            if not task._finished or (
                task._delivery is not None and task._delivery.pending
            ):
                return
            self._tasks.discard(task)
            self._keys = {
                key: value for key, value in self._keys.items() if value is not task
            }

    def close(self) -> Future[None]:
        """Dispose interest now and close after physical work, without blocking.

        Returns:
            A future for cleanup; repeated closes return the same future.
        """
        with self._lock:
            self._closed = True
            for owner in self._owners:
                with owner.lock:
                    owner.resources.discard(self)
            self._owners.clear()
            for task in tuple(self._tasks):
                task.cancel()
            self._maybe_close()
            return self._cleanup

    def _maybe_close(self) -> None:
        if not self._closed or self._physical or self._cleanup_started:
            return
        self._cleanup_started = True
        if self._pool is None:
            self._cleanup.set_result(None)
            return
        self._pool.submit(self._close_on_lane)
        self._pool.shutdown(wait=False)

    def _close_on_lane(self) -> None:
        try:
            if self._value is not _UNOPENED:
                self._dispose(cast("T", self._value))
        except Exception as exc:
            self._cleanup.set_exception(exc)
        else:
            self._cleanup.set_result(None)
        finally:
            self._value = _UNOPENED
