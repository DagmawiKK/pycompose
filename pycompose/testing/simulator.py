"""A deterministic stand-in for the runtime's scheduler.

The simulated loop has a virtual clock that jumps straight to the next timer
whenever nothing is ready, so a test that sleeps for an hour takes no time.
Threads run inline, randomness is seeded, and tasks run in the order they were
scheduled, so the same test makes the same run every time.
"""

from __future__ import annotations

import asyncio
import random
import selectors
from collections.abc import Callable, Coroutine
from concurrent.futures import Executor, Future
from typing import Any, TypeVar, cast

from pycompose.runtime.scheduler import Scheduler

__all__ = ["InlineExecutor", "SimulatedLoop", "Simulator"]

T = TypeVar("T")


class InlineExecutor(Executor):
    """Runs each submitted call immediately, on the calling thread."""

    def submit(self, fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> Future[T]:
        future: Future[T] = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:
            future.set_exception(exc)
        return future


class _VirtualSelector(selectors.BaseSelector):
    """A real selector whose waits advance the loop's virtual clock instead."""

    def __init__(self, loop: SimulatedLoop) -> None:
        self._real = selectors.DefaultSelector()
        self._loop = loop

    def register(
        self, fileobj: Any, events: int, data: Any = None
    ) -> selectors.SelectorKey:
        return self._real.register(fileobj, events, data)

    def unregister(self, fileobj: Any) -> selectors.SelectorKey:
        return self._real.unregister(fileobj)

    def modify(
        self, fileobj: Any, events: int, data: Any = None
    ) -> selectors.SelectorKey:
        return self._real.modify(fileobj, events, data)

    def get_map(self) -> Any:
        return self._real.get_map()

    def close(self) -> None:
        self._real.close()

    def select(
        self, timeout: float | None = None
    ) -> list[tuple[selectors.SelectorKey, int]]:
        events = self._real.select(0)
        if events or timeout is None:
            return events
        self._loop.advance(timeout)
        return []


class SimulatedLoop(asyncio.SelectorEventLoop):
    """An event loop on a virtual clock that starts at zero."""

    def __init__(self) -> None:
        self._now = 0.0
        super().__init__(selector=_VirtualSelector(self))

    def time(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        """Move the virtual clock forward.

        Args:
            seconds: How far to move it; never negative.
        """
        self._now += max(0.0, seconds)


class Simulator:
    """A simulated loop and a scheduler over it, for one deterministic run.

    Args:
        seed: Seeds the scheduler's random source.
    """

    def __init__(self, seed: int = 0) -> None:
        self.loop = SimulatedLoop()
        self.failures: list[tuple[str, BaseException]] = []
        self.loop.set_exception_handler(
            lambda _loop, context: self.failures.append(
                ("loop", context.get("exception") or RuntimeError(context["message"]))
            )
        )
        inline = InlineExecutor()
        self.scheduler = Scheduler(
            self.loop,
            io=inline,
            cpu=inline,
            storage=inline,
            rng=random.Random(seed),
            report=lambda scope, error: self.failures.append((scope, error)),
        )

    def run(self, work: Coroutine[Any, Any, T]) -> T:
        """Run ``work`` to completion on the simulated loop.

        Args:
            work: The coroutine to run.

        Returns:
            What it returned.
        """
        return self.loop.run_until_complete(work)

    def settle(self) -> None:
        """Run every task until none can make progress without the clock moving."""

        async def idle() -> None:
            # A ready queue that stays empty across a full pass means nothing
            # else can run until a timer fires or input arrives.
            while cast("Any", self.loop)._ready:
                await asyncio.sleep(0)

        self.loop.run_until_complete(idle())

    def close(self) -> None:
        """Close the loop and the scheduler."""
        self.scheduler.close()
        self.loop.close()
