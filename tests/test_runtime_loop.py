"""The loop thread: one owner, ordered work, no deadlock on re-entry."""

from __future__ import annotations

import threading

import pytest

from pycompose.errors import BridgeError
from pycompose.runtime.loop import LoopThread


def _loop() -> LoopThread:
    return LoopThread(lambda *_: None)


def test_calls_run_on_the_loop_thread_and_return_their_result() -> None:
    loop = _loop()
    try:
        name = loop.call(lambda: threading.current_thread().name)
        assert name == "pycompose-loop"
        assert loop.call(sum, [1, 2, 3]) == 6
    finally:
        loop.stop()


def test_posted_work_runs_in_the_order_it_was_posted() -> None:
    loop = _loop()
    seen: list[int] = []
    try:
        for value in range(20):
            loop.post(seen.append, value)
        loop.call(lambda: None)
        assert seen == list(range(20))
    finally:
        loop.stop()


def test_a_call_made_on_the_loop_thread_runs_inline() -> None:
    loop = _loop()
    try:
        assert loop.call(lambda: loop.call(lambda: "nested")) == "nested"
    finally:
        loop.stop()


def test_a_failing_call_raises_in_the_caller() -> None:
    loop = _loop()
    try:
        with pytest.raises(ZeroDivisionError):
            loop.call(lambda: 1 / 0)
    finally:
        loop.stop()


def test_the_heartbeat_is_fresh_while_the_loop_runs() -> None:
    loop = _loop()
    try:
        assert loop.since_heartbeat() < 5
    finally:
        loop.stop()


def test_a_stopped_loop_refuses_calls() -> None:
    loop = _loop()
    loop.stop()
    with pytest.raises(BridgeError, match="stopped"):
        loop.call(lambda: None)
