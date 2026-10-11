"""state.Actions: pure action registry."""

from __future__ import annotations

import pytest

from pycompose.core import ROOT_ID, Node
from pycompose.errors import StateError
from pycompose.state import Actions, State


def test_register_and_dispatch() -> None:
    root = Node(id=ROOT_ID, type="Column")
    initial = State(root=root, version=0)
    actions = Actions()

    def increment(s: State, payload: dict) -> State:
        return State(root=s.root, version=s.version + payload.get("by", 1))

    actions.register("increment", increment)
    result = actions.dispatch("increment", initial, {"by": 2})
    assert result.version == 2
    assert result.root == root


def test_dispatch_unknown_action_raises_state_error() -> None:
    root = Node(id=ROOT_ID, type="Text")
    initial = State(root=root, version=0)
    actions = Actions()
    with pytest.raises(StateError) as excinfo:
        actions.dispatch("missing", initial, {})
    assert "action_id='missing'" in str(excinfo.value)


def test_register_duplicate_overwrites_or_is_ok() -> None:
    root = Node(id=ROOT_ID, type="Text")
    initial = State(root=root, version=0)
    actions = Actions()

    def v1(s: State, _payload: dict) -> State:
        return State(root=s.root, version=s.version + 1)

    def v2(s: State, _payload: dict) -> State:
        return State(root=s.root, version=s.version + 10)

    actions.register("x", v1)
    actions.register("x", v2)
    result = actions.dispatch("x", initial, {})
    assert result.version == 10
