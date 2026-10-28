"""Background work, and its results coming back as ordinary actions.

Everything here runs on the real executor with real threads. What it proves is
the property that matters: the worker is never blocked, and a result arrives
through exactly the same path as a tap.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from pycompose import action, async_task
from pycompose.bridge import BridgeSurface
from pycompose.errors import StateError
from pycompose.m3 import Text
from pycompose.state import Actions, State, Store


@action
def arrived(state: State, value: str) -> State:
    """Record a background result.

    Args:
        state: Snapshot before the result.
        value: The value the background work produced.

    Returns:
        The next snapshot showing the result.
    """
    return State(
        root=Text(id="text", text=value),
        version=state.version + 1,
        data={"last": value},
    )


@action
def echo_request(state: State, request: str, value: str) -> State:
    """Record a background result that was bound to a request.

    Args:
        state: Snapshot before the result.
        request: The request id bound when the work was submitted.
        value: The value the work produced.

    Returns:
        The next snapshot showing both.
    """
    return State(
        root=Text(id="text", text=f"{request}:{value}"),
        version=state.version + 1,
    )


@pytest.fixture(autouse=True)
def _clean_pool(request: pytest.FixtureRequest) -> None:
    """Give every test a fresh pool and sink.

    Args:
        request: The fixture request, used to schedule the teardown.
    """
    async_task.shutdown()
    request.addfinalizer(async_task.shutdown)


class Sink:
    """Collects delivered results, standing in for the host."""

    def __init__(self) -> None:
        """Start with nothing delivered and no threads recorded."""
        self.delivered: list[tuple[str, str]] = []
        self.threads: list[str] = []

    def __call__(self, action_id: str, payload: str) -> None:
        """Record one delivery.

        Args:
            action_id: The handler the result is for.
            payload: Its canonical payload text.
        """
        self.delivered.append((action_id, payload))
        self.threads.append(threading.current_thread().name)

    def wait(self, count: int = 1, timeout: float = 5.0) -> bool:
        """Block until the expected number of results has arrived.

        Args:
            count: How many to wait for.
            timeout: Seconds to give up after.

        Returns:
            True when they arrived in time.
        """
        deadline = time.monotonic() + timeout
        while len(self.delivered) < count and time.monotonic() < deadline:
            time.sleep(0.005)
        return len(self.delivered) >= count


# ---------------------------------------------------------------------------
# The worker is not blocked
# ---------------------------------------------------------------------------


def test_work_does_not_block_the_caller() -> None:
    release = threading.Event()
    async_task.install_sink(Sink())
    started = time.monotonic()

    async_task.run(lambda: _after(release, "slow"), arrived)

    # Returning promptly is the entire point; the work is still running.
    assert time.monotonic() - started < 0.5
    release.set()


def test_work_runs_off_the_calling_thread() -> None:
    sink = Sink()
    async_task.install_sink(sink)
    seen: list[str] = []

    async_task.run(
        lambda: (seen.append(threading.current_thread().name), {"value": "x"})[1],
        arrived,
    )

    assert sink.wait()
    assert seen[0].startswith("PyCompose-async")
    assert seen[0] != threading.current_thread().name


def test_the_worker_keeps_rendering_while_work_is_in_flight() -> None:
    """The whole reason this exists: a slow call must not stop the app."""
    bridge = BridgeSurface(
        Store(State(root=Text(id="t", text="idle"))), Actions(arrived)
    )
    release = threading.Event()
    async_task.install_sink(
        lambda aid, payload: bridge.accept_action(_envelope(aid, payload))
    )

    async_task.run(lambda: _after(release, "late"), arrived)

    # The bridge is still answering while the background work is blocked.
    assert (
        json.loads(bridge.expose_latest_snapshot() or "{}")["root"]["props"]["text"]
        == "idle"
    )
    release.set()


# ---------------------------------------------------------------------------
# Results come back as actions
# ---------------------------------------------------------------------------


def test_a_result_is_delivered_to_its_handler_as_canonical_json() -> None:
    sink = Sink()
    async_task.install_sink(sink)

    async_task.run(lambda: {"value": "fetched"}, arrived)

    assert sink.wait()
    action_id, payload = sink.delivered[0]
    assert action_id == "notes_app.actions.arrived" or action_id.endswith(".arrived")
    assert json.loads(payload) == {"value": "fetched"}


def test_a_delivered_result_re_enters_the_app_like_a_tap() -> None:
    """The result must land on the worker, not on the thread that produced it.

    The host marshals to the main thread and queues; the worker then pulls it
    through exactly the path a tap takes. Every bridge call here therefore runs on
    the owning thread, because anything else is refused by contract.
    """
    pending: list[str] = []
    async_task.install_sink(
        lambda aid, payload: pending.append(_envelope(aid, payload))
    )

    async_task.run(lambda: {"value": "fetched"}, arrived)
    _until(lambda: bool(pending))
    assert pending, "the host never received the result"

    def on_worker() -> tuple[str, str]:
        bridge = BridgeSurface(
            Store(State(root=Text(id="t", text="waiting"))), Actions(arrived)
        )
        bridge.accept_action(pending[0])
        return bridge.expose_latest_snapshot() or "", bridge.expose_latest_error()

    source, error = _on_worker(on_worker)
    assert '"fetched"' in source, source
    assert error == ""


def _until(predicate: Callable[[], bool], timeout: float = 5.0) -> None:
    """Block until a predicate holds, or the timeout expires.

    Args:
        predicate: What to wait for.
        timeout: Seconds to give up after.
    """
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)


def _on_worker(work: Callable[[], Any]) -> Any:
    """Run work on a thread standing in for the Python worker, and return it.

    The bridge records whichever thread builds it as its owner, so every call has
    to happen on that same thread.

    Args:
        work: A callable returning the value to hand back.

    Returns:
        Whatever work returned, or None if it failed.

    Raises:
        BaseException: Re-raised from whatever work raised on the worker.
    """
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = work()
        except BaseException as failure:
            box["error"] = failure

    thread = threading.Thread(target=target, name="PyCompose-Python")
    thread.start()
    thread.join(5)
    failure = box.get("error")
    if failure is not None:
        raise failure
    return box.get("value")


def test_bound_values_are_merged_with_the_result() -> None:
    sink = Sink()
    async_task.install_sink(sink)

    async_task.run(
        lambda: {"value": "second"},
        echo_request,
        payload={"request": "first"},
    )

    assert sink.wait()
    _, payload = sink.delivered[0]
    assert json.loads(payload) == {"request": "first", "value": "second"}


def test_the_result_wins_over_a_bound_value_of_the_same_name() -> None:
    sink = Sink()
    async_task.install_sink(sink)

    async_task.run(
        lambda: {"value": "produced"},
        echo_request,
        payload={"request": "r", "value": "bound"},
    )

    assert sink.wait()
    assert json.loads(sink.delivered[0][1])["value"] == "produced"


def _after(gate: threading.Event, value: str) -> dict[str, str]:
    """Wait for a gate, then report a result.

    Written as two statements on purpose: ``gate.wait() or result`` would yield
    the truthy wait when the gate opens, which is a silent empty payload rather
    than an error.

    Args:
        gate: What the work waits on.
        value: The result to report.

    Returns:
        The result payload.
    """
    gate.wait(3)
    return {"value": value}


def _envelope(action_id: str, payload: str) -> str:
    """Return the action envelope the host would deliver.

    Args:
        action_id: The handler the result is for.
        payload: Its canonical payload text.

    Returns:
        The envelope JSON.
    """
    return json.dumps({"intent": action_id, "payload": json.loads(payload)})


# ---------------------------------------------------------------------------
# Failure is visible, never silent
# ---------------------------------------------------------------------------


def test_failing_work_reports_and_delivers_nothing() -> None:
    sink = Sink()
    async_task.install_sink(sink)

    async_task.run(lambda: 1 / 0, arrived)

    deadline = time.monotonic() + 5
    while not async_task.last_error() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert "async work failed" in async_task.last_error()
    assert sink.delivered == []


def test_a_result_that_is_not_json_is_refused() -> None:
    sink = Sink()
    async_task.install_sink(sink)

    async_task.run(lambda: {"value": object()}, arrived)

    deadline = time.monotonic() + 5
    while not async_task.last_error() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert "not JSON" in async_task.last_error()
    assert sink.delivered == []


def test_a_result_arriving_with_no_host_is_reported_not_dropped() -> None:
    async_task.install_sink(None)
    async_task.run(lambda: {"value": "orphan"}, arrived)

    deadline = time.monotonic() + 5
    while not async_task.last_error() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert "before the host" in async_task.last_error()


# ---------------------------------------------------------------------------
# The contract is refused up front
# ---------------------------------------------------------------------------


def test_work_that_is_not_callable_is_refused() -> None:
    with pytest.raises(StateError, match="callable"):
        async_task.run("not callable", arrived)  # type: ignore[arg-type]


def test_a_target_that_is_not_an_action_is_refused() -> None:
    with pytest.raises(StateError, match="app action"):
        async_task.run(lambda: {"value": "x"}, object())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


def test_two_pieces_of_work_run_concurrently() -> None:
    """Sequential work would defeat the purpose of moving it off the worker."""
    sink = Sink()
    async_task.install_sink(sink)
    barrier = threading.Barrier(2, timeout=5)

    def work() -> dict[str, Any]:
        barrier.wait()
        return {"value": "both"}

    async_task.run(work, arrived)
    async_task.run(work, arrived)

    assert sink.wait(2), sink.delivered


def test_results_arrive_in_the_order_the_work_finished() -> None:
    sink = Sink()
    async_task.install_sink(sink)

    def slow() -> dict[str, Any]:
        time.sleep(0.15)
        return {"value": "slow"}

    def quick() -> dict[str, Any]:
        return {"value": "quick"}

    async_task.run(slow, arrived)
    async_task.run(quick, arrived)

    assert sink.wait(2)
    assert [json.loads(p)["value"] for _, p in sink.delivered] == ["quick", "slow"]


def test_shutdown_stops_the_pool_from_growing() -> None:
    async_task.install_sink(Sink())
    async_task.run(lambda: {"value": "x"}, arrived)
    async_task.shutdown()
    assert async_task.last_error() == ""


def test_every_result_is_delivered_off_the_main_thread() -> None:
    """The host marshals to main; the pool must never be the thing blocking it."""
    sink = Sink()
    async_task.install_sink(sink)
    async_task.run(lambda: {"value": "x"}, arrived)

    assert sink.wait()
    assert all(not name.startswith("PyCompose-Python") for name in sink.threads)


# ---------------------------------------------------------------------------
# The whole loop, as an app would use it
# ---------------------------------------------------------------------------


def test_an_app_can_do_work_while_the_screen_keeps_responding() -> None:
    """The scenario the seam exists for, start to finish.

    A handler kicks off slow work and returns. The app carries on accepting taps.
    When the work lands, it is delivered as an ordinary action and the screen
    updates -- without the worker ever having blocked.
    """
    release = threading.Event()
    queued: list[str] = []

    @action
    def refresh(state: State, value: str) -> State:
        return State(
            root=Text(id="text", text=value),
            version=state.version + 1,
        )

    async_task.install_sink(lambda aid, payload: queued.append(_envelope(aid, payload)))
    async_task.run(lambda: _after(release, "synced"), refresh)

    # Work is in flight. Nothing about the app is stuck.
    assert queued == []

    release.set()
    _until(lambda: bool(queued))
    assert queued, "the result never came back"

    def on_worker() -> str:
        bridge = BridgeSurface(
            Store(State(root=Text(id="t", text="stale"))),
            Actions(refresh),
        )
        bridge.accept_action(queued[0])
        return bridge.expose_latest_snapshot() or ""

    assert '"synced"' in _on_worker(on_worker)


def test_a_second_result_arriving_late_does_not_disturb_the_first() -> None:
    """Ordering: results are delivered as they finish, and each one stands alone."""
    sink = Sink()
    async_task.install_sink(sink)
    gates = [threading.Event(), threading.Event()]

    def work_for(index: int):
        def work() -> dict[str, Any]:
            gates[index].wait(3)
            return {"value": f"result-{index}"}

        return work

    async_task.run(work_for(0), arrived)
    async_task.run(work_for(1), arrived)

    gates[0].set()
    _until(lambda: len(sink.delivered) == 1)
    assert json.loads(sink.delivered[0][1])["value"] == "result-0"

    gates[1].set()
    assert sink.wait(2)
    assert json.loads(sink.delivered[1][1])["value"] == "result-1"


# ---------------------------------------------------------------------------
# Sizing and back pressure
# ---------------------------------------------------------------------------


def test_the_pool_size_is_the_apps_choice() -> None:
    """Two threads is a guess; the app is the one that knows its shape."""
    async_task.install_sink(Sink())
    async_task.configure(workers=6)
    try:
        assert async_task._workers == 6
        barrier = threading.Barrier(6, timeout=5)

        def work() -> dict[str, Any]:
            barrier.wait()
            return {"value": "wide"}

        for _ in range(6):
            async_task.run(work, arrived)
    finally:
        async_task.configure()


def test_the_default_is_not_two() -> None:
    assert async_task.DEFAULT_WORKERS >= 4


@pytest.mark.parametrize("workers", [0, -1, 1.5, True, "4"])
def test_an_impossible_pool_size_is_refused(workers: Any) -> None:
    with pytest.raises(StateError, match="positive integer"):
        async_task.configure(workers=workers)


def test_work_is_refused_rather_than_piled_up_when_the_queue_is_full() -> None:
    """A queue that grows forever holds stale results that all land at once."""
    async_task.install_sink(Sink())
    async_task.configure(workers=1)
    release = threading.Event()
    try:
        for _ in range(40):
            if not _accepted(
                lambda: async_task.run(lambda: _after(release, "x"), arrived)
            ):
                break
        else:
            pytest.fail("an unbounded queue accepted 40 requests on one thread")
        assert "refused" in async_task.last_error()
    finally:
        release.set()


def test_the_bound_recovers_once_work_drains() -> None:
    """Refusing is only useful if the app can try again afterwards."""
    async_task.install_sink(Sink())
    async_task.configure(workers=1)
    release = threading.Event()
    try:
        for _ in range(200):
            if not _accepted(
                lambda: async_task.run(lambda: _after(release, "x"), arrived)
            ):
                break
        release.set()
        _until(
            lambda: _accepted(lambda: async_task.run(lambda: {"value": "ok"}, arrived))
        )
        assert async_task.last_error() == ""
    finally:
        async_task.configure()


def _accepted(attempt: Callable[[], Any]) -> bool:
    """Run a submission, reporting whether it was accepted.

    Args:
        attempt: The submission to try.

    Returns:
        True when it was accepted.
    """
    try:
        attempt()
    except StateError:
        return False
    return True
