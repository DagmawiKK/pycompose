"""AppDriver drives an app as its host does, with no device (plan 31 §18.7)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pycompose_testing.driver import AppDriver

NOTES = Path(__file__).resolve().parents[3] / "examples/notes"


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


def test_the_first_screen_is_composed_as_the_device_composes_it() -> None:
    import json

    from pycompose_cli.project import load_project
    from pycompose_cli.render import first_screen

    snapshot = json.loads(first_screen(load_project(NOTES)))
    assert snapshot["root"]["type"]
    assert snapshot["schemaVersion"]


def test_a_walked_screen_renders_to_a_png_and_semantics(tmp_path: Path) -> None:
    import json
    import os
    import shutil

    if os.environ.get("PYCOMPOSE_RENDER_TESTS") != "1":
        pytest.skip("rendering runs the app's generated host under Gradle")
    root = tmp_path / "notes"
    shutil.copytree(NOTES, root, ignore=shutil.ignore_patterns(".pycompose"))
    with AppDriver(root, route="notes") as app:
        app.click(type="FloatingActionButton")
        image, semantics = app.render(tmp_path / "out", "editor")
    assert image.read_bytes().startswith(b"\x89PNG")
    dump = json.loads(semantics.read_text())
    assert dump["reports"] == []
    assert "Title" in json.dumps(dump["windows"])
