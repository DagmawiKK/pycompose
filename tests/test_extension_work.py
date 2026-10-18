"""Owned work through the public contributor interface and real worker actions."""

import threading
from concurrent.futures import CancelledError

import pytest

from pycompose.errors import StateError
from pycompose.extensions import Resource


def test_serial_resource_opens_uses_and_closes_on_its_owned_lane() -> None:
    threads: list[int] = []

    def acquire() -> list[str]:
        threads.append(threading.get_ident())
        return []

    def update(values: list[str]) -> tuple[str, ...]:
        threads.append(threading.get_ident())
        values.append("saved")
        return tuple(values)

    def dispose(values: list[str]) -> None:
        assert values == ["saved"]
        threads.append(threading.get_ident())

    resource = Resource(acquire, close=dispose)
    assert resource.submit(update).result(timeout=3) == ("saved",)
    resource.close().result(timeout=3)
    assert len(set(threads)) == 1
    assert threads[0] != threading.get_ident()
    with pytest.raises(StateError, match="closed"):
        resource.submit(update)


def test_obsolete_running_work_still_counts_towards_the_bound() -> None:
    entered, release = threading.Event(), threading.Event()
    resource = Resource(lambda: None, close=lambda _: None, capacity=1)

    def work(_: None) -> str:
        entered.set()
        assert release.wait(3)
        return "physical side effect completed"

    task = resource.submit(work)
    try:
        assert entered.wait(3)
        task.cancel()
        with pytest.raises(StateError, match="full"):
            resource.submit(lambda _: "not admitted")
    finally:
        release.set()
        resource.close().result(timeout=3)
    assert task.result(timeout=3) == "physical side effect completed"


def test_queued_cancellation_never_calls_the_library() -> None:
    entered, release = threading.Event(), threading.Event()
    resource = Resource(lambda: None, close=lambda _: None)

    def wait(_: None) -> None:
        entered.set()
        assert release.wait(3)

    first = resource.submit(wait)
    try:
        assert entered.wait(3)
        second = resource.submit(lambda _: pytest.fail("cancelled work executed"))
        second.cancel()
        with pytest.raises(CancelledError):
            second.result(timeout=3)
    finally:
        release.set()
        first.result(timeout=3)
        resource.close().result(timeout=3)


def test_single_flight_keeps_one_physical_operation_for_a_key() -> None:
    entered, release = threading.Event(), threading.Event()
    resource = Resource(lambda: None, close=lambda _: None)

    def wait(_: None) -> str:
        entered.set()
        assert release.wait(3)
        return "one operation"

    try:
        first = resource.submit(wait, key="page", policy="single_flight")
        assert entered.wait(3)
        second = resource.submit(
            lambda _: pytest.fail("duplicate operation"),
            key="page",
            policy="single_flight",
        )
        assert first is second
        release.set()
        assert second.result(timeout=3) == "one operation"
    finally:
        release.set()
        resource.close().result(timeout=3)


def test_cancelled_queue_items_keep_capacity_until_the_executor_dequeues_them() -> None:
    entered, release = threading.Event(), threading.Event()
    resource = Resource(lambda: None, close=lambda _: None, capacity=2)

    def wait(_: None) -> None:
        entered.set()
        assert release.wait(3)

    try:
        first = resource.submit(wait)
        assert entered.wait(3)
        second = resource.submit(lambda _: pytest.fail("cancelled operation ran"))
        second.cancel()
        with pytest.raises(StateError, match="full"):
            resource.submit(lambda _: "would grow the physical queue")
        release.set()
        first.result(timeout=3)
    finally:
        release.set()
        resource.close().result(timeout=3)
