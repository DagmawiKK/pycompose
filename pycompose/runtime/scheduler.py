"""The scheduler: the runtime's only door to time, randomness, tasks and threads."""

from __future__ import annotations

import asyncio
import functools
import random
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from typing import Literal, TypeVar

from pycompose.runtime.scope import Report, Scope

__all__ = ["Scheduler", "ThreadKind"]

T = TypeVar("T")
ThreadKind = Literal["io", "cpu"]


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
        rng: The session's only source of randomness.
        report: Receives every supervised failure, with its scope's name.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        *,
        io: Executor,
        cpu: Executor,
        rng: random.Random,
        report: Report,
    ) -> None:
        self.loop = loop
        self._executors: dict[ThreadKind, Executor] = {"io": io, "cpu": cpu}
        self._random = rng
        self._report = report

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

    async def to_thread(
        self, kind: ThreadKind, work: Callable[..., T], *args: object
    ) -> T:
        """Run ``work`` on the pool for ``kind`` and resume on the loop with its result.

        Cancelling the awaiting task discards the result; the call itself runs
        to completion, because a thread cannot be stopped.

        Args:
            kind: ``"io"`` for waiting, ``"cpu"`` for computing.
            work: The callable to run off the loop.
            *args: Its arguments.

        Returns:
            What ``work`` returned.
        """
        return await self.loop.run_in_executor(
            self._executors[kind], functools.partial(work, *args)
        )

    def close(self) -> None:
        """Stop both pools, dropping work that has not started."""
        for executor in self._executors.values():
            executor.shutdown(wait=False, cancel_futures=True)
