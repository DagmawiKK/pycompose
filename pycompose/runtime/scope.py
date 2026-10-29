"""Supervised task scopes: a failing task is reported and never cancels another."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from pycompose.errors import StateError

__all__ = ["Scope"]

Report = Callable[[str, BaseException], None]


class Scope:
    """A named set of tasks with one owner, closed together.

    This is supervision, not ``asyncio.TaskGroup``: a task group cancels every
    sibling when one task raises, so one failed refresh would stop the stream
    feeding a screen. Here a failure is handed to ``report`` and the other
    tasks keep running. Closing the scope cancels everything still running
    and waits for it, so no task outlives its owner.

    Args:
        name: What owns the scope, for diagnostics.
        report: Receives the scope's name and each task's failure.
    """

    def __init__(self, name: str, report: Report) -> None:
        self.name = name
        self._report = report
        self._tasks: set[asyncio.Task[Any]] = set()
        self._closed = False

    @property
    def running(self) -> int:
        """How many tasks are still running.

        Returns:
            The number of unfinished tasks.
        """
        return len(self._tasks)

    @property
    def closed(self) -> bool:
        """Whether the scope has been closed.

        Returns:
            True once :meth:`close` has started.
        """
        return self._closed

    def spawn(self, work: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        """Start ``work`` on the running loop, owned by this scope.

        Args:
            work: The coroutine to run.

        Returns:
            Its task.

        Raises:
            StateError: If the scope is closed; the coroutine is closed unrun.
        """
        if self._closed:
            work.close()
            raise StateError("a closed scope cannot start work", scope=self.name)
        task = asyncio.get_running_loop().create_task(work)
        self._tasks.add(task)
        task.add_done_callback(self._finished)
        return task

    def _finished(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        failure = task.exception()
        if failure is not None:
            self._report(self.name, failure)

    async def close(self) -> None:
        """Cancel every running task and wait until each has ended."""
        self._closed = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
