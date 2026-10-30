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
from pathlib import Path
from typing import Any

import pytest
from pycompose_testing.driver import AppDriver

from pycompose.material3 import TextField
from pycompose.model.catalog.lock import SCHEMA_VERSION

APP = Path(__file__).resolve().parents[1] / "examples" / "notes" / "app"
SCHEMA = json.loads(Path("schema/catalog.lock.json").read_text())
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
    assert props["onSelectionChange"] == {
        "type": "actionId",
        # The caret travels back as the caret offset, on the wire under "value".
        # Declared since 1.10.0, when callbacks stopped being bare actionIds.
        "payload": [{"name": "value", "type": "integer"}],
    }
    for name in ("selection", "onSelectionChange"):
        assert "default" not in props[name]
        assert "required" not in props[name]


def test_the_schema_grew_without_becoming_permissive() -> None:
    """The version moved; permissive shapes are still absent."""
    # The catalog's version is whatever the runtime stamps into the wire. It
    # moves with every batch; the test pins the *congruence*, not the number.
    assert SCHEMA["schemaVersion"] == SCHEMA_VERSION
    assert {"1.5.0", "1.6.0", "1.7.0"} <= set(SCHEMA["supportedSchemaVersions"])
    # The legacy field remains scalar-only. The state-based search helper has
    # a separate atomic editing contract; it must not silently change this API.
    assert "selectionStart" not in SCHEMA["components"]["TextField"]["props"]
    assert "selectionEnd" not in SCHEMA["components"]["TextField"]["props"]


# ---------------------------------------------------------------------------
# The real app, end to end
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def editor(request: pytest.FixtureRequest) -> Any:
    """Import the Notes editor's intents the way the worker imports the app.

    Args:
        request: The fixture request, used to schedule the teardown.

    Returns:
        The editor's view model module.
    """
    sys.path.insert(0, str(APP))
    request.addfinalizer(
        lambda: [
            sys.modules.pop(n) for n in list(sys.modules) if n.startswith("notes_app")
        ]
    )
    request.addfinalizer(lambda: sys.path.remove(str(APP)))
    import notes_app.view_models.note_editor as module

    return module


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


def _snapshot_on_editor() -> dict[str, Any]:
    """Start the app, open a new note, and return the editor's snapshot.

    Returns:
        The parsed snapshot.
    """
    with AppDriver(APP.parent) as app:
        app.click(type="FloatingActionButton")
        return app.snapshot()


def test_a_field_without_the_caret_declares_no_selection(editor: Any) -> None:
    """Uncontrolled is the default, and it declares nothing at all."""
    unbound = TextField(
        id="f",
        value="hi",
        on_value_change=editor.SetBody.bind(note_id=1),
    )
    assert unbound.props.get("selection") is None
    assert unbound.props.get("onSelectionChange") is None


def test_declaring_both_halves_puts_them_in_the_props(editor: Any) -> None:
    bound = TextField(
        id="f",
        value="hi",
        selection=2,
        on_value_change=editor.SetBody.bind(note_id=1),
        on_selection_change=editor.SetBodyCaret,
    )
    assert bound.props["selection"] == 2
    assert bound.props["onSelectionChange"]


def test_the_editor_publishes_two_controlled_fields() -> None:
    """Which is the whole claim of Path A, in one assertion."""
    published = _fields(_snapshot_on_editor()["root"], "TextField")
    assert len(published) == 2
    for field in published:
        assert "selection" in field["props"]
        assert field["props"]["onSelectionChange"]


def test_the_caret_lives_in_the_saved_state() -> None:
    """State the app owns is in the snapshot, so a test can assert on it."""
    editor = _snapshot_on_editor()["metadata"]["data"]["stack"][-1]["state"]
    assert editor["titleCaret"] == 0
    assert editor["bodyCaret"] == 0


# ---------------------------------------------------------------------------
# What this cannot do, stated so nobody discovers it later
# ---------------------------------------------------------------------------


def test_a_caret_moved_without_the_text_changing_is_not_reported() -> None:
    """A real limit, documented rather than discovered.

    Material3's TextField has no selection callback, so the caret is read back
    from the same callback that reports the text. Moving the caret with an arrow
    key produces no text change and so no event. Making it observable needs
    TextFieldState, which arrived in material3 1.4.0-alpha; this project is on
    compose-bom 2026.09.00, which resolves to 1.4.x.
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
