"""AppDriver drives an app as its host does, with no device (plan 31 §18.7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pycompose.testing.driver import AppDriver

NOTES = Path(__file__).resolve().parents[1] / "examples/notes"


def test_a_test_walks_the_notes_app_screen_by_screen() -> None:
    with AppDriver(NOTES, route="notes") as app:
        assert "No notes yet." in app.texts()
        # The button's navigate effect is echoed back, as the host does.
        app.click(type="FloatingActionButton")
        assert "Title" in app.texts()
        app.edit("Groceries", text="Title")
        title = app.find(text="Title", type="TextField")
        assert title["props"]["value"] == "Groceries"


def test_a_selector_must_name_exactly_one_node() -> None:
    with AppDriver(NOTES, route="notes") as app:
        with pytest.raises(AssertionError, match="2 nodes match"):
            app.find(type="NavigationBarItem")
        with pytest.raises(AssertionError, match="has no onClick"):
            app.act("onClick", app.find(text="Notes"))
