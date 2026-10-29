"""The loop thread: the one thread that owns a session's state.

The host never runs Python state code itself. It posts work to this thread,
either waiting for the answer (:meth:`LoopThread.call`) or not
(:meth:`LoopThread.post`), and this thread runs it in the order it arrived.
One writer means no data races by construction.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time
from collections.abc import Callable
from typing import TypeVar

from pycompose.errors import BridgeError
from pycompose.runtime.scheduler import Scheduler
from pycompose.runtime.scope import Report

__all__ = ["LoopThread"]

T = TypeVar("T")

HEARTBEAT = 0.5
"""Seconds between heartbeats; a host watching the loop allows several to pass."""


class LoopThread:
    """A started event loop on its own thread, with the session's scheduler.

    Args:
        report: Receives every supervised failure on this loop.
        name: The thread's name, for stack dumps.
    """

    def __init__(self, report: Report, *, name: str = "pycompose-loop") -> None:
        self.loop = asyncio.new_event_loop()
        self.scheduler = Scheduler.real(self.loop, report)
        self._report = report
        self._beat = time.monotonic()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()
        self._ready.wait()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        # What asyncio cannot hand to anyone -- a failure nobody awaited -- is
        # supervised like any other: reported, never lost to a log line.
        self.loop.set_exception_handler(
            lambda _loop, context: self._report(
                "loop", context.get("exception") or RuntimeError(context["message"])
            )
        )
        # Held, since the loop keeps only a weak reference to its tasks.
        self._heartbeat_task = self.loop.create_task(self._heartbeat())
        self.loop.call_soon(self._ready.set)
        try:
            self.loop.run_forever()
        finally:
            # Whatever is still running ends here, cancelled, as asyncio.run ends it.
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            self.loop.run_until_complete(
                asyncio.gather(*pending, return_exceptions=True)
            )
            self.loop.close()

    async def _heartbeat(self) -> None:
        while True:
            self._beat = time.monotonic()
            await asyncio.sleep(HEARTBEAT)

    @property
    def on_loop(self) -> bool:
        """Whether the caller is running on this loop's thread.

        Returns:
            True on the loop thread.
        """
        return threading.current_thread() is self._thread

    def since_heartbeat(self) -> float:
        """Return how long ago the loop last proved it was running.

        Returns:
            Seconds since the last heartbeat; a large value means the loop is stuck.
        """
        return time.monotonic() - self._beat

    def idle(self) -> bool:
        """Report whether every task the session started has finished.

        Returns:
            True when only the loop's own heartbeat is still running.
        """
        return self.call(
            lambda: all(
                task is self._heartbeat_task or task.done()
                for task in asyncio.all_tasks(self.loop)
            )
        )

    def call(self, work: Callable[..., T], *args: object) -> T:
        """Run ``work`` on the loop thread and wait for its result.

        Called from the loop thread itself, it runs inline, so work that calls
        back into the session cannot deadlock.

        Args:
            work: The callable to run.
            *args: Its arguments.

        Returns:
            What ``work`` returned.

        Raises:
            BridgeError: If the loop has stopped.
        """
        if self.on_loop:
            return work(*args)
        if self.loop.is_closed() or not self._thread.is_alive():
            raise BridgeError("the session loop has stopped")
        future: concurrent.futures.Future[T] = concurrent.futures.Future()

        def run() -> None:
            if not future.set_running_or_notify_cancel():
                return
            try:
                future.set_result(work(*args))
            except BaseException as exc:
                future.set_exception(exc)

        self.loop.call_soon_threadsafe(run)
        return future.result()

    def post(self, work: Callable[..., object], *args: object) -> None:
        """Queue ``work`` on the loop thread without waiting.

        Args:
            work: The callable to run.
            *args: Its arguments.
        """
        self.loop.call_soon_threadsafe(work, *args)

    def stop(self) -> None:
        """Stop the loop, release the scheduler's threads and join the loop thread."""
        if self.loop.is_closed():
            return
        self.scheduler.close()
        self.loop.call_soon_threadsafe(self.loop.stop)
        if not self.on_loop:
            self._thread.join()
