"""state.State: frozen snapshot."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from pycompose.core import ROOT_ID, Node
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
