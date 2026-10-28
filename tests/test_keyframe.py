"""A whole snapshot is a bounded keyframe: its size does not follow the list."""

from __future__ import annotations

from types import ModuleType

import pytest
from notes_support import Host, a_store, load_notes_app

KEYFRAME_BUDGET = 128 * 1024
"""Bytes a whole notes snapshot may take, at any number of notes."""


@pytest.fixture(scope="module")
def app() -> ModuleType:
    return load_notes_app()


def keyframe(app: ModuleType, count: int) -> int:
    notes = [(n, f"Note {n}", "body") for n in range(1, count + 1)]
    host = Host(app, repo=a_store(notes))
    return len(host.envelope().encode())


def test_a_whole_snapshot_stays_the_same_size_at_any_list_length(
    app: ModuleType,
) -> None:
    small, large = keyframe(app, 200), keyframe(app, 5_000)

    assert large <= KEYFRAME_BUDGET
    # Only the counts, and the digits of the notes in the window, grow with it.
    assert large - small < 1024
