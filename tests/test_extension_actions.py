"""Contributor outcomes enter State through the existing worker action queue."""

import gc
import json
import queue
import threading
import time
import weakref
from collections.abc import Callable
from typing import TypedDict

import pytest

from pycompose import action, async_task
from pycompose.bridge import BridgeSurface
from pycompose.errors import StateError
from pycompose.extensions import Resource, Task
from pycompose.m3 import Text
from pycompose.state import Actions, State, Store


class Value(TypedDict):
    value: str


class Failure(TypedDict):
    error: str


@action
def arrived(state: State, payload: Value) -> State:
    return State(
        root=Text(id="result", text=payload["value"]), version=state.version + 1
    )


@action
def failed(state: State, payload: Failure) -> State:
    return State(
        root=Text(id="result", text=payload["error"]), version=state.version + 1
    )


def envelope(action_id: str, payload: dict[str, str]) -> str:
    return json.dumps({"actionId": action_id, "payload": payload})


def application(
    resource: Resource[None], operation: Callable[[str], str], **options: object
) -> tuple[BridgeSurface, queue.Queue[str], list[Task[str]]]:
    pending: queue.Queue[str] = queue.Queue()
    async_task.install_sink(
        lambda aid, data: pending.put(envelope(aid, json.loads(data)))
    )
    tasks: list[Task[str]] = []

    @action
    def launch(state: State, payload: Value) -> State:
        tasks.append(
            resource.submit(
                lambda _: operation(payload["value"]),
                success=arrived,
                failure=failed,
                encode=lambda value: {"value": value},
                **options,  # type: ignore[arg-type]
            )
        )
        return state

    surface = BridgeSurface(
        Store(State(root=Text(id="result", text="idle"))),
        Actions(launch, arrived, failed),
    )
    surface.accept_action(envelope(launch.name, {"value": "first"}))
    return surface, pending, tasks


def test_outcomes_are_not_state_changes_until_the_worker_admits_them() -> None:
    resource = Resource(lambda: None, close=lambda _: None)
    try:
        surface, pending, tasks = application(resource, str.upper)
        assert tasks[0].result(timeout=3) == "FIRST"
        assert '"idle"' in (surface.expose_latest_snapshot() or "")
        completion = pending.get(timeout=3)
        surface.accept_action(completion)
        assert '"FIRST"' in (surface.expose_latest_snapshot() or "")
        assert surface.expose_latest_error() == ""
        snapshot = surface.expose_latest_snapshot()
        surface.accept_action(completion)
        assert surface.expose_latest_snapshot() == snapshot  # at most once
    finally:
        resource.close().result(timeout=3)
        async_task.install_sink(None)


def test_library_failure_reaches_a_declared_action_without_exception_secrets() -> None:
    resource = Resource(lambda: None, close=lambda _: None)

    def broken(_: str) -> str:
        raise ValueError("secret bearer-token and private URL")

    try:
        surface, pending, tasks = application(resource, broken)
        with pytest.raises(ValueError):
            tasks[0].result(timeout=3)
        surface.accept_action(pending.get(timeout=3))
        assert '"ValueError"' in (surface.expose_latest_snapshot() or "")
        assert "secret" not in surface.expose_latest_error()
    finally:
        resource.close().result(timeout=3)
        async_task.install_sink(None)


def test_cancellation_after_enqueue_still_prevents_worker_mutation() -> None:
    resource = Resource(lambda: None, close=lambda _: None)
    try:
        surface, pending, tasks = application(resource, str.upper)
        completion = pending.get(timeout=3)
        tasks[0].cancel()
        surface.accept_action(completion)
        assert '"idle"' in (surface.expose_latest_snapshot() or "")
    finally:
        resource.close().result(timeout=3)
        async_task.install_sink(None)


def test_slow_library_work_does_not_block_unrelated_ui_actions() -> None:
    entered, release = threading.Event(), threading.Event()
    resource = Resource(lambda: None, close=lambda _: None)

    def slow(value: str) -> str:
        entered.set()
        assert release.wait(3)
        return value

    try:
        surface, pending, _ = application(resource, slow)
        assert entered.wait(3)
        surface.accept_action(envelope(arrived.name, {"value": "tapped"}))
        assert '"tapped"' in (surface.expose_latest_snapshot() or "")
        assert pending.empty()
    finally:
        release.set()
        resource.close().result(timeout=3)
        async_task.install_sink(None)


def test_completed_but_unacknowledged_outcomes_are_bounded() -> None:
    resource = Resource(lambda: None, close=lambda _: None, capacity=1)
    try:
        surface, pending, tasks = application(resource, str.upper)
        assert tasks[0].result(timeout=3) == "FIRST"
        with pytest.raises(StateError, match="full"):
            resource.submit(lambda _: None)
        surface.accept_action(pending.get(timeout=3))
        assert resource.submit(lambda _: "admitted").result(timeout=3) == "admitted"
    finally:
        resource.close().result(timeout=3)
        async_task.install_sink(None)


def test_ambiguous_payload_cannot_consume_a_registered_completion() -> None:
    resource = Resource(lambda: None, close=lambda _: None)
    try:
        surface, pending, _ = application(resource, str.upper)
        completion = pending.get(timeout=3)
        identity = json.loads(completion)["actionId"]
        ambiguous = (
            f'{{"actionId":"{identity}","payload":{{"value":"altered"}},'
            '"payload":{"value":"FIRST"}}'
        )
        surface.accept_action(ambiguous)
        assert '"idle"' in (surface.expose_latest_snapshot() or "")
        surface.accept_action(completion)
        assert '"FIRST"' in (surface.expose_latest_snapshot() or "")
    finally:
        resource.close().result(timeout=3)
        async_task.install_sink(None)


def test_latest_supersedes_an_outcome_already_waiting_in_the_host_queue() -> None:
    resource = Resource(lambda: None, close=lambda _: None)
    try:
        surface, pending, _ = application(
            resource, str.upper, key="query", policy="latest"
        )
        old = pending.get(timeout=3)
        surface.accept_action(
            envelope(
                f"{__name__}.launch",
                {"value": "second"},
            )
        )
        new = pending.get(timeout=3)
        surface.accept_action(new)
        surface.accept_action(old)
        assert '"SECOND"' in (surface.expose_latest_snapshot() or "")
    finally:
        resource.close().result(timeout=3)
        async_task.install_sink(None)


def test_single_flight_does_not_reuse_another_surface_epochs_completion() -> None:
    entered, release = threading.Event(), threading.Event()
    resource = Resource(lambda: None, close=lambda _: None)

    def slow(value: str) -> str:
        entered.set()
        assert release.wait(3)
        return value.upper()

    try:
        previous, pending, old_tasks = application(
            resource, slow, key="page", policy="single_flight"
        )
        assert entered.wait(3)
        successor, pending, new_tasks = application(
            resource, str.upper, key="page", policy="single_flight"
        )
        previous.close(successor=successor)
        assert new_tasks[0] is not old_tasks[0]
        release.set()
        successor.accept_action(pending.get(timeout=3))
        assert '"FIRST"' in (successor.expose_latest_snapshot() or "")
    finally:
        release.set()
        resource.close().result(timeout=3)
        async_task.install_sink(None)


def test_native_queue_rejection_settles_outcome_and_allows_retry() -> None:
    entered, release = threading.Event(), threading.Event()
    resource = Resource(lambda: None, close=lambda _: None, capacity=1)

    def slow(value: str) -> str:
        entered.set()
        assert release.wait(3)
        return value

    try:
        surface, pending, tasks = application(resource, slow)
        assert entered.wait(3)
        async_task.install_sink(
            lambda *_: pytest.fail("extension used unacknowledged legacy delivery"),
            admission=lambda *_: False,
        )
        release.set()
        assert tasks[0].result(timeout=3) == "first"
        assert tasks[0].diagnostic == "extension outcome rejected: StateError"
        assert "extension outcome rejected" in surface.expose_latest_error()
        assert pending.empty()
        assert resource.submit(lambda _: "retry").result(timeout=3) == "retry"
    finally:
        release.set()
        resource.close().result(timeout=3)
        async_task.install_sink(None)


def test_explicitly_disposed_resources_are_not_retained_by_a_live_session() -> None:
    disposed = []
    references = []

    @action
    def temporary(state: State, payload: Value) -> State:
        resource = Resource(lambda: None, close=lambda _: None)
        resource.submit(lambda _: payload["value"])
        disposed.append(resource.close())
        references.append(weakref.ref(resource))
        return state

    surface = BridgeSurface(
        Store(State(root=Text(id="result", text="idle"))), Actions(temporary)
    )
    try:
        for _ in range(3):
            surface.accept_action(envelope(temporary.name, {"value": "temporary"}))
        for cleanup in disposed:
            cleanup.result(timeout=3)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            gc.collect()
            if all(reference() is None for reference in references):
                break
            threading.Event().wait(0.01)
        assert all(reference() is None for reference in references)
    finally:
        surface.close()
