"""Loaded fields: refilled by the app, never saved for process death."""

from __future__ import annotations

import pytest

from pycompose.errors import StateError
from pycompose.state import AppState, Loaded


class Screen(AppState):
    query: str = ""
    rows: Loaded[tuple[str, ...]] = ()


def test_a_loaded_field_is_left_out_of_the_saved_state() -> None:
    state = Screen(query="cats", rows=("a", "b"))
    assert Screen.codec.encode(state) == {"query": "cats"}


def test_restoring_refills_a_loaded_field_with_its_default() -> None:
    restored = Screen.codec.decode({"query": "cats"})
    assert restored == Screen(query="cats", rows=())


def test_saved_bytes_naming_a_loaded_field_are_refused() -> None:
    with pytest.raises(StateError, match="never saved"):
        Screen.codec.decode({"query": "cats", "rows": ["a"]})


def test_a_loaded_field_needs_a_default() -> None:
    class Broken(AppState):
        rows: Loaded[tuple[str, ...]]

    with pytest.raises(StateError, match="needs a default"):
        Broken.codec.encode(Broken(rows=()))
