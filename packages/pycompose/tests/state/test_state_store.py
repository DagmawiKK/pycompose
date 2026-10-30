"""state.Store: mutable holder with snapshot and rebuild semantics."""

from __future__ import annotations

from pycompose.model.nodes import ROOT_ID, Node
from pycompose.state import State, Store


def _root_text(text: str) -> Node:
    return Node(id=ROOT_ID, type="Text", props={"text": text})


def test_store_initial_value() -> None:
    root = _root_text("hi")
    store = Store(State(root=root, version=0))
    assert store.value.root == root
    assert store.value.version == 0


def test_mutate_passes_current_and_replaces() -> None:
    root = _root_text("a")
    store = Store(State(root=root, version=0))

    def reducer(s: State) -> State:
        return State(root=s.root, version=s.version + 1)

    new_state = store.mutate(reducer)
    assert new_state.version == 1
    assert store.value.version == 1


def test_mutate_does_not_retain_old_snapshot_reference() -> None:
    root = _root_text("a")
    store = Store(State(root=root, version=0))
    original = store.value

    def reducer(s: State) -> State:
        return State(root=_root_text("b"), version=s.version + 1)

    store.mutate(reducer)
    assert original.root == _root_text("a")
    assert store.value.root == _root_text("b")


def test_request_rebuild_noop_when_equal() -> None:
    root = _root_text("a")
    store = Store(State(root=root, version=2))
    current = store.value
    store.request_rebuild(current)
    assert store.value is current


def test_request_rebuild_replaces_when_different() -> None:
    root = _root_text("a")
    store = Store(State(root=root, version=1))
    new_state = State(root=_root_text("b"), version=5)
    store.request_rebuild(new_state)
    assert store.value is new_state
