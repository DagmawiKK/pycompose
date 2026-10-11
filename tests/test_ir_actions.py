"""ir.actions: Action and ActionQueue."""

from __future__ import annotations

import pytest

from pycompose.ir import Action, ActionQueue


def test_action_fields() -> None:
    a = Action(action_id="increment", payload={"by": 1}, version=5)
    assert a.action_id == "increment"
    assert a.payload == {"by": 1}
    assert a.version == 5


def test_action_queue_fifo_and_empty() -> None:
    q = ActionQueue()
    assert q.empty()
    assert q.size() == 0
    q.push(Action(action_id="a", payload={}, version=0))
    q.push(Action(action_id="b", payload={}, version=1))
    assert q.size() == 2
    assert not q.empty()
    first = q.pop()
    assert first.action_id == "a"
    second = q.pop()
    assert second.action_id == "b"
    assert q.empty()
    with pytest.raises(IndexError):
        q.pop()
