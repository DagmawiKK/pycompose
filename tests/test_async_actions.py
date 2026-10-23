"""Async actions run off the worker and come back as the fields they changed."""

from __future__ import annotations

import asyncio
import json
import queue
from collections.abc import AsyncIterator, Iterator

import pytest

from pycompose import Registry, action, async_task
from pycompose.bridge import BridgeSurface
from pycompose.core.node import Node
from pycompose.errors import StateError
from pycompose.m3 import Text
from pycompose.state import AppState, State, Store


class Shell(AppState):
    status: str = "idle"
    count: int = 0


actions = Registry()


@actions
async def load(session: Shell, page: int) -> Shell:
    await asyncio.sleep(0)
    return session.evolve(status=f"page {page}")


@actions
async def stream(session: Shell) -> AsyncIterator[Shell]:
    yield session.evolve(status="loading")
    await asyncio.sleep(0)
    yield session.evolve(status="done")


@actions
async def search(session: Shell, query: str) -> Shell:
    await asyncio.sleep(0.2 if query == "slow" else 0)
    return session.evolve(status=query)


@actions
def bump(session: Shell) -> Shell:
    return session.evolve(count=session.count + 1)


def view(session: Shell) -> Node:
    return Text(text=f"{session.status}/{session.count}")


@pytest.fixture
def delivered() -> Iterator[queue.Queue[str]]:
    pending: queue.Queue[str] = queue.Queue()
    async_task.install_sink(
        lambda aid, payload: pending.put(
            json.dumps({"actionId": aid, "payload": json.loads(payload)})
        )
    )
    yield pending
    async_task.shutdown()


def bridge() -> BridgeSurface:
    actions.install_view(view)
    shell = Shell()
    return BridgeSurface(Store(State(root=view(shell), app=shell)), actions)


def text(surface: BridgeSurface) -> str:
    return json.loads(surface.expose_latest_snapshot() or "")["root"]["props"]["text"]


def test_an_async_action_comes_back_as_the_fields_it_changed(
    delivered: queue.Queue[str],
) -> None:
    surface = bridge()
    surface.accept_action(json.dumps({"actionId": load.name, "payload": {"page": 2}}))
    assert text(surface) == "idle/0"
    surface.accept_action(json.dumps({"actionId": bump.name, "payload": {}}))

    surface.accept_action(delivered.get(timeout=3))

    # The count the user moved meanwhile stands; only the status was changed.
    assert text(surface) == "page 2/1"


def test_an_async_generator_streams_each_state(delivered: queue.Queue[str]) -> None:
    surface = bridge()
    surface.accept_action(json.dumps({"actionId": stream.name, "payload": {}}))

    surface.accept_action(delivered.get(timeout=3))
    assert text(surface) == "loading/0"
    surface.accept_action(delivered.get(timeout=3))
    assert text(surface) == "done/0"


def test_an_async_action_must_take_the_shell() -> None:
    async def fetch(state: State) -> State:
        return state

    with pytest.raises(StateError, match="shell first"):
        action(fetch)


def test_a_newer_run_cancels_the_one_it_supersedes(
    delivered: queue.Queue[str],
) -> None:
    surface = bridge()
    for query in ("slow", "fast"):
        surface.accept_action(
            json.dumps({"actionId": search.name, "payload": {"query": query}})
        )

    surface.accept_action(delivered.get(timeout=3))

    assert text(surface) == "fast/0"
    with pytest.raises(queue.Empty):
        delivered.get(timeout=0.4)
