"""Controlled TextField: the caret the app owns.

Path A, in one component. Most of what looks like ``remember`` in a Compose UI is
really presence in the tree or a value derived from props -- both of which the
snapshot already determines. TextField's caret was the genuine exception, and the
fix was to promote it into the snapshot rather than to cache it host-side.

Declaring ``selection`` and ``onSelectionChange`` makes the field controlled.
Omit either and it stays exactly as it was: Compose owns the caret and the app
never sees it. No host state is involved on either path.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from pycompose import AppContext, install_context
from pycompose.m3 import TextField

APP = Path(__file__).resolve().parents[1] / "examples" / "notes" / "app"
SCHEMA = json.loads(Path("schema/components.json").read_text())
ADAPTER = Path(
    "android/host/src/main/kotlin/com/pycompose/host/ui/BuiltinComponents.kt"
)


# ---------------------------------------------------------------------------
# The schema
# ---------------------------------------------------------------------------


def test_the_caret_is_declared_optional() -> None:
    """Optional is the point: absence is what selects the other path."""
    props = SCHEMA["components"]["TextField"]["props"]
    assert props["selection"] == {"type": "integer"}
    assert props["onSelectionChange"] == {"type": "actionId"}
    for name in ("selection", "onSelectionChange"):
        assert "default" not in props[name]
        assert "required" not in props[name]


def test_the_schema_grew_without_becoming_permissive() -> None:
    """Two props were added and the version moved; nothing else changed shape."""
    assert SCHEMA["schemaVersion"] == "1.7.0"
    assert {"1.5.0", "1.6.0"} <= set(SCHEMA["supportedSchemaVersions"])
    # The range form I tried first is not there, because the event channel
    # carries one scalar and a range is two.
    assert "selectionStart" not in json.dumps(SCHEMA)


# ---------------------------------------------------------------------------
# The real app, end to end
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def notes(request: pytest.FixtureRequest) -> Any:
    """Import the Notes app the way the worker does.

    Args:
        request: The fixture request, used to schedule the teardown.

    Returns:
        The app entrypoint module.
    """
    sys.path.insert(0, str(APP))
    request.addfinalizer(lambda: sys.modules.pop("main", None))
    request.addfinalizer(lambda: sys.path.remove(str(APP)))
    import main

    return main


def _fields(root: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """Return every node of a type under a root.

    Args:
        root: The root node.
        kind: The node type to collect.

    Returns:
        Each matching node, in document order.
    """
    found: list[dict[str, Any]] = []
    stack = [root]
    while stack:
        node = stack.pop(0)
        if node.get("type") == kind:
            found.append(node)
        stack = list(node.get("children", [])) + stack
    return found


def _snapshot_on_editor(notes: Any) -> dict[str, Any]:
    """Start the app on the editor with one note, and return its snapshot.

    Args:
        notes: The app entrypoint.

    Returns:
        The parsed first snapshot.
    """
    from notes_app.container import AppContainer
    from notes_app.data.notes_repo import FileNotesRepo
    from notes_app.domain import Notes
    from notes_app.domain.models import Note

    from pycompose.bridge import BridgeSurface
    from pycompose.repository import Document, use_root
    from pycompose.state import State as Snapshot
    from pycompose.state import Store

    use_root(Path(tempfile.mkdtemp()))
    repo = FileNotesRepo(
        Document("notes.json", Note, directory=Path(tempfile.mkdtemp()))
    )
    repo.store([Note(1, "Only", "hello")])
    container = AppContainer(Notes(repo))
    notes.actions.install_container(container)
    install_context(
        AppContext(actions=notes.actions, container=container, notes=container.notes)
    )
    assert Snapshot is not None
    surface = BridgeSurface(
        Store(notes.build(route="note:1", restore="", container=container)),
        notes.actions,
    )
    return json.loads(surface.expose_latest_snapshot())


def test_a_field_without_the_caret_declares_no_selection(notes: Any) -> None:
    """Uncontrolled is the default, and it declares nothing at all."""
    unbound = TextField(
        id="f",
        value="hi",
        on_value_change=notes.actions.set_body.bind(id="b", note_id=1),
    )
    assert unbound.props.get("selection") is None
    assert unbound.props.get("onSelectionChange") is None


def test_declaring_both_halves_puts_them_in_the_props(notes: Any) -> None:
    bound = TextField(
        id="f",
        value="hi",
        selection=2,
        on_value_change=notes.actions.set_body.bind(id="b", note_id=1),
        on_selection_change=notes.actions.set_body_caret.bind(id="b", note_id=1),
    )
    assert bound.props["selection"] == 2
    assert bound.props["onSelectionChange"]


def test_the_editor_publishes_two_controlled_fields(notes: Any) -> None:
    """Which is the whole claim of Path A, in one assertion."""
    published = _fields(_snapshot_on_editor(notes)["root"], "TextField")
    assert len(published) == 2
    for field in published:
        assert "selection" in field["props"]
        assert field["props"]["onSelectionChange"]


def test_the_caret_lives_in_the_published_shell(notes: Any) -> None:
    """State the app owns is in the snapshot, so a test can assert on it."""
    data = _snapshot_on_editor(notes)["metadata"]["data"]
    assert data["titleCaret"] == 0
    assert data["bodyCaret"] == 0


# ---------------------------------------------------------------------------
# What this cannot do, stated so nobody discovers it later
# ---------------------------------------------------------------------------


def test_a_caret_moved_without_the_text_changing_is_not_reported() -> None:
    """A real limit, documented rather than discovered.

    Material3's TextField has no selection callback, so the caret is read back
    from the same callback that reports the text. Moving the caret with an arrow
    key produces no text change and so no event. Making it observable needs
    TextFieldState, which arrived in material3 1.4.0-alpha; this project is on
    compose-bom 2025.01.01, which resolves to 1.3.x.
    """
    assert "no selection callback of its" in ADAPTER.read_text()


def test_the_event_channel_still_carries_one_value() -> None:
    """A caret is one integer. A selection *range* would be two, and cannot be.

    That is why the schema carries an offset rather than a range, and it is the
    boundary that would have to move for richer text selection to work.
    """
    renderer = Path(
        "android/renderer/src/main/kotlin/com/pycompose/renderer/Renderer.kt"
    ).read_text()
    assert "value: JsonPrimitive" in renderer
