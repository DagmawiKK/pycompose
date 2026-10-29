"""Supervised scopes: failures stay isolated, and nothing outlives its scope."""

from __future__ import annotations

import asyncio

import pytest

from pycompose.errors import StateError
from pycompose.runtime import Scope


def _scope(reports: list[tuple[str, str]]) -> Scope:
    return Scope("screen", lambda name, error: reports.append((name, str(error))))


def test_a_failing_task_is_reported_and_its_siblings_keep_running() -> None:
    reports: list[tuple[str, str]] = []

    async def run() -> list[int]:
        scope = _scope(reports)
        seen: list[int] = []

        async def stream() -> None:
            for value in range(3):
                await asyncio.sleep(0)
                seen.append(value)

        async def fail() -> None:
            raise ValueError("refresh failed")

        scope.spawn(stream())
        scope.spawn(fail())
        for _ in range(5):
            await asyncio.sleep(0)
        await scope.close()
        return seen

    assert asyncio.run(run()) == [0, 1, 2]
    assert reports == [("screen", "refresh failed")]


def test_closing_cancels_every_task_and_waits_for_it() -> None:
    async def run() -> tuple[int, bool]:
        scope = _scope([])
        cleaned = asyncio.Event()

        async def forever() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        scope.spawn(forever())
        scope.spawn(forever())
        await asyncio.sleep(0)
        await scope.close()
        return scope.running, cleaned.is_set()

    assert asyncio.run(run()) == (0, True)


def test_a_cancelled_task_is_not_reported_as_a_failure() -> None:
    reports: list[tuple[str, str]] = []

    async def run() -> None:
        scope = _scope(reports)
        task = scope.spawn(asyncio.sleep(10))
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        await scope.close()

    asyncio.run(run())
    assert reports == []


def test_a_closed_scope_refuses_new_work() -> None:
    async def run() -> None:
        scope = _scope([])
        await scope.close()
        work = asyncio.sleep(0)
        with pytest.raises(StateError, match="closed scope"):
            scope.spawn(work)

    asyncio.run(run())
