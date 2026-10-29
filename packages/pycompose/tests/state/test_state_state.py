"""state.State: frozen snapshot."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from pycompose.core import ROOT_ID, Node
from pycompose.errors import StateError
from pycompose.state import State


def test_state_is_frozen() -> None:
    root = Node(id=ROOT_ID, type="Text")
    state = State(root=root, version=0)
    with pytest.raises(FrozenInstanceError):
        state.root = Node(id=ROOT_ID, type="Column")  # type: ignore[misc]


def test_state_uses_slots() -> None:
    root = Node(id=ROOT_ID, type="Text")
    state = State(root=root)
    assert hasattr(state, "__slots__")


def test_state_defaults() -> None:
    root = Node(id=ROOT_ID, type="Text")
    state = State(root=root)
    assert state.version == 0
    assert state.data is None


def test_app_data_is_detached_frozen_json_owned_by_the_snapshot() -> None:
    root = Node(id=ROOT_ID, type="Text")
    tasks = [{"id": 1, "done": False}]
    state = State(root=root, data={"tasks": tasks, "filter": "all"})
    tasks.append({"id": 2, "done": True})
    assert len(state.data["tasks"]) == 1
    assert state == State(
        root=root, data={"tasks": [{"id": 1, "done": False}], "filter": "all"}
    )
    assert state != replace(state, data={"tasks": [], "filter": "all"})
    with pytest.raises(TypeError):
        state.data["filter"] = "done"  # type: ignore[index]


@pytest.mark.parametrize(
    "data",
    [
        ["not", "a", "mapping"],
        {"tasks": {1, 2}},
        {"ratio": float("nan")},
        {"callback": len},
    ],
)
def test_app_data_rejects_anything_that_is_not_json(data: object) -> None:
    root = Node(id=ROOT_ID, type="Text")
    with pytest.raises(StateError, match="state.data"):
        State(root=root, data=data)  # type: ignore[arg-type]
