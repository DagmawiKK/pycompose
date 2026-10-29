"""The scheduler and its deterministic simulation."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from pycompose_testing.simulator import Simulator

from pycompose.runtime.scheduler import Scheduler, to_thread


def test_simulated_time_jumps_to_the_next_timer() -> None:
    sim = Simulator()

    async def wait_an_hour() -> float:
        await asyncio.sleep(3600)
        return sim.scheduler.now()

    started = time.monotonic()
    assert sim.run(wait_an_hour()) == 3600
    assert time.monotonic() - started < 1
    sim.close()


def test_the_same_seed_gives_the_same_run() -> None:
    def draws(seed: int) -> list[float]:
        sim = Simulator(seed)
        values = [sim.scheduler.random().random() for _ in range(3)]
        sim.close()
        return values

    assert draws(7) == draws(7)
    assert draws(7) != draws(8)


def test_threads_run_inline_under_simulation() -> None:
    sim = Simulator()

    async def compute() -> tuple[int, str]:
        value = await sim.scheduler.to_thread("cpu", sum, [1, 2, 3])
        return value, threading.current_thread().name

    assert sim.run(compute()) == (6, threading.current_thread().name)
    with pytest.raises(ZeroDivisionError):
        sim.run(sim.scheduler.to_thread("io", lambda: 1 / 0))
    sim.close()


def test_settle_runs_every_task_that_can_progress() -> None:
    sim = Simulator()
    order: list[str] = []

    async def start() -> None:
        scope = sim.scheduler.scope("screen")

        async def first() -> None:
            order.append("first")
            scope.spawn(second())

        async def second() -> None:
            await asyncio.sleep(0)
            order.append("second")

        async def later() -> None:
            await asyncio.sleep(5)
            order.append("later")

        scope.spawn(first())
        scope.spawn(later())

    sim.run(start())
    sim.settle()
    assert order == ["first", "second"]
    sim.close()


def test_supervised_failures_reach_the_report() -> None:
    sim = Simulator()

    async def start() -> None:
        async def fail() -> None:
            raise RuntimeError("boom")

        sim.scheduler.scope("screen").spawn(fail())

    sim.run(start())
    sim.settle()
    assert [(scope, str(error)) for scope, error in sim.failures] == [
        ("screen", "boom")
    ]
    sim.close()


def test_the_real_scheduler_keeps_cpu_work_on_one_named_thread() -> None:
    loop = asyncio.new_event_loop()
    scheduler = Scheduler.real(loop, lambda *_: None)

    async def names() -> set[str]:
        found = await asyncio.gather(
            *(
                scheduler.to_thread("cpu", lambda: threading.current_thread().name)
                for _ in range(4)
            )
        )
        return set(found)

    found = loop.run_until_complete(names())
    assert len(found) == 1
    assert next(iter(found)).startswith("pycompose-cpu")
    scheduler.close()
    loop.close()


def test_app_code_reaches_the_session_pools_through_to_thread() -> None:
    from pycompose.app import to_thread
    from pycompose.errors import StateError

    sim = Simulator()

    async def summed() -> int:
        return await to_thread("io", sum, [1, 2, 3])

    assert sim.run(summed()) == 6

    async def elsewhere() -> int:
        return await to_thread("cpu", sum, [1])

    with pytest.raises(StateError, match="session's loop"):
        asyncio.run(elsewhere())
    sim.close()


def test_storage_calls_run_in_order_even_when_nobody_waits() -> None:
    from pycompose.runtime.loop import LoopThread

    written: list[int] = []
    loop = LoopThread(lambda *_: None)
    try:

        def queue() -> None:
            for n in range(50):
                # Asked for, never awaited: each still runs, in the order asked.
                to_thread("storage", written.append, n)

        loop.call(queue)
    finally:
        loop.stop()  # finishes what the storage thread was asked to do
    assert written == list(range(50))


def test_a_cancelled_waiter_never_unqueues_its_call() -> None:
    sim = Simulator()
    done: list[str] = []

    async def gives_up() -> None:
        waiting = asyncio.ensure_future(to_thread("storage", done.append, "write"))
        waiting.cancel()
        await asyncio.sleep(0)

    sim.run(gives_up())
    sim.settle()
    assert done == ["write"]
    sim.close()


def test_a_failure_nobody_waits_for_is_reported() -> None:
    sim = Simulator()

    def fails() -> None:
        raise OSError("disk full")

    async def forgets() -> None:
        to_thread("storage", fails)
        await asyncio.sleep(0)

    sim.run(forgets())
    sim.settle()
    import gc

    gc.collect()
    assert [type(error) for _, error in sim.failures] == [OSError]
    sim.close()
