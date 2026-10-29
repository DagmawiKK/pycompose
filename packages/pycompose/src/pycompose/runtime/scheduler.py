"""The scheduler: the runtime's only door to time, randomness, tasks and threads."""

from __future__ import annotations

import asyncio
import functools
import random
import weakref
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from typing import Any, Literal, TypeVar, cast

from pycompose.errors import StateError
from pycompose.runtime.scope import Report, Scope

__all__ = ["Scheduler", "ThreadKind", "to_thread"]

T = TypeVar("T")
ThreadKind = Literal["io", "cpu", "storage"]

_SCHEDULERS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Scheduler] = (
    weakref.WeakKeyDictionary()
)
"""The scheduler each session loop runs with, so app code can find its pools."""


class Scheduler:
    """Time, randomness, scopes and threads for one session, injected as a unit.

    Production builds one with :meth:`real`; tests build one over a simulated
    loop with inline executors and a seeded random source, so every run of a
    test is the same run.

    Args:
        loop: The event loop that owns the session's state.
        io: Runs blocking calls that mostly wait (files, sockets, libraries
            without async support).
        cpu: Runs computation. A single thread, so computation never queues
            up behind the GIL in front of the loop.
        storage: One thread for resources that belong to a single thread, such
            as a SQLite connection; its calls run one at a time, in order.
        rng: The session's only source of randomness.
        report: Receives every supervised failure, with its scope's name.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        *,
        io: Executor,
        cpu: Executor,
        storage: Executor,
        rng: random.Random,
        report: Report,
    ) -> None:
        self.loop = loop
        self._executors: dict[ThreadKind, Executor] = {
            "io": io,
            "cpu": cpu,
            "storage": storage,
        }
        self._random = rng
        self._report = report
        _SCHEDULERS[loop] = self

    @classmethod
    def real(
        cls, loop: asyncio.AbstractEventLoop, report: Report, *, io_workers: int = 4
    ) -> Scheduler:
        """Build the production scheduler over ``loop``.

        Args:
            loop: The session's event loop.
            report: Receives every supervised failure.
            io_workers: Threads for blocking I/O.

        Returns:
            A scheduler with real thread pools and an unseeded random source.
        """
        return cls(
            loop,
            io=ThreadPoolExecutor(io_workers, thread_name_prefix="pycompose-io"),
            cpu=ThreadPoolExecutor(1, thread_name_prefix="pycompose-cpu"),
            storage=ThreadPoolExecutor(1, thread_name_prefix="pycompose-storage"),
            rng=random.Random(),
            report=report,
        )

    def now(self) -> float:
        """Return the loop's monotonic time in seconds.

        Returns:
            The current time on the session's clock.
        """
        return self.loop.time()

    def random(self) -> random.Random:
        """Return the session's random source.

        Returns:
            The one ``Random`` every part of the session draws from.
        """
        return self._random

    def scope(self, name: str) -> Scope:
        """Open a supervised scope whose failures this scheduler reports.

        Args:
            name: What owns the scope, for diagnostics.

        Returns:
            A new, open scope.
        """
        return Scope(name, self._report)

    def submit(
        self, kind: ThreadKind, work: Callable[..., T], *args: object
    ) -> asyncio.Future[T]:
        """Queue ``work`` on the pool for ``kind`` now; await the result if wanted.

        The call is queued here, not when someone awaits it, and cancelling a
        waiter never unqueues it: a write that was asked for always happens, in
        the order asked on a one-thread pool. A failure nobody waits for any
        more reaches the session's report.

        Args:
            kind: ``"io"``, ``"cpu"`` or ``"storage"``.
            work: The callable to run off the loop.
            *args: Its arguments.

        Returns:
            A future of what ``work`` returned.
        """
        job = self.loop.run_in_executor(
            self._executors[kind], functools.partial(work, *args)
        )
        waiter = asyncio.shield(job)

        def abandoned(outer: asyncio.Future[T]) -> None:
            if outer.cancelled():
                job.add_done_callback(self._report_failure)

        waiter.add_done_callback(abandoned)
        return waiter

    def _report_failure(self, job: asyncio.Future[Any]) -> None:
        if not job.cancelled() and job.exception() is not None:
            self._report("thread", cast("BaseException", job.exception()))

    async def to_thread(
        self, kind: ThreadKind, work: Callable[..., T], *args: object
    ) -> T:
        """Run ``work`` on the pool for ``kind`` and resume on the loop with its result.

        Args:
            kind: ``"io"``, ``"cpu"`` or ``"storage"``.
            work: The callable to run off the loop.
            *args: Its arguments.

        Returns:
            What ``work`` returned.
        """
        return await self.submit(kind, work, *args)

    def close(self) -> None:
        """Stop the pools; the storage thread first finishes what was queued."""
        for kind, executor in self._executors.items():
            # Queued storage calls are writes that were asked for: finish them.
            executor.shutdown(wait=kind == "storage", cancel_futures=kind != "storage")


def to_thread(
    kind: ThreadKind, work: Callable[..., T], *args: object
) -> asyncio.Future[T]:
    """Run ``work`` off the loop on the session's pool for ``kind``.

    ``"io"`` is for calls that mostly wait, such as a blocking HTTP client;
    ``"cpu"`` is for computation, on one thread so it never queues in front of
    the loop; ``"storage"`` is one thread for a resource that belongs to a
    single thread, such as a SQLite connection, so its calls run in order.

    The call is queued at once, whether or not anyone awaits it, and runs even
    if the awaiting task is cancelled: a write that was asked for happens.
    Await the result to use it; a failure nobody waits for reaches ``on_error``.

    Args:
        kind: ``"io"``, ``"cpu"`` or ``"storage"``.
        work: The callable to run.
        *args: Its arguments.

    Returns:
        A future of what ``work`` returned.

    Raises:
        StateError: Outside a session's loop.
    """
    try:
        scheduler = _SCHEDULERS.get(asyncio.get_running_loop())
    except RuntimeError:
        scheduler = None
    if scheduler is None:
        raise StateError("to_thread runs only on a session's loop")
    return scheduler.submit(kind, work, *args)
