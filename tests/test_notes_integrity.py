"""Integrity, rehydration, size and hot-reload behaviour of the notes example."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from pycompose.app.intents import intent_class
from pycompose.app.navigation import route_key
from pycompose.bridge.session import RuntimeSession
from pycompose.contract.catalog import SCHEMA_VERSION
from pycompose.repository import use_root
from pycompose.runtime.loop import LoopThread
from pycompose.testing.driver import AppDriver

if TYPE_CHECKING:
    from types import ModuleType

from notes_support import (
    APP,
    SEEDED,
    Host,
    a_store,
    data,
    held_of,
    live_intents,
    load_notes_app,
    nodes,
    stack,
    titles_of,
)


@pytest.fixture(scope="module")
def app() -> ModuleType:
    """Import the Notes app exactly as the Android worker does."""
    return load_notes_app()


def editor(note_id: int) -> str:
    """Return the key the host keeps for one note's editor.

    Args:
        note_id: The note.

    Returns:
        The route's canonical JSON.
    """
    from notes_app.routes import EditorRoute

    return route_key(EditorRoute(note_id=note_id))


def saved(host: Host) -> str:
    """Return the bytes the host would keep for process death.

    Args:
        host: The running host.

    Returns:
        The whole published stack, as JSON.
    """
    return json.dumps(host.snapshot()["metadata"]["data"])


def test_an_emptied_store_stays_empty_rather_than_reseeding(
    app: ModuleType,
) -> None:
    """Deleting everything is a decision, not a state the app recovers from."""
    disk = a_store()
    host = Host(app, repo=disk)
    host.tap("DeleteNote", {"note_id": 1})
    host.tap("DeleteNote", {"note_id": 2})
    assert host.titles == []

    assert titles_of(Host(app, repo=disk, restore=saved(host))) == []


def test_dark_mode_is_the_themes_job_not_the_snapshots(app: ModuleType) -> None:
    """Colours are theme roles, so a change of appearance changes no snapshot."""
    host = Host(app)
    before = host.snapshot()
    assert "containerColor" not in before["root"]["props"]
    host.lifecycle(
        "onConfigChanged",
        darkMode=True,
        orientation="portrait",
        locale="en-US",
        density=2.0,
    )
    assert host.snapshot()["root"] == before["root"]


def test_the_notes_never_cross_the_boundary(app: ModuleType) -> None:
    """The Bundle carries the screens' small state and nothing else.

    Anything the host saves has to fit in a transaction buffer measured in
    kilobytes. Saving the notes would mean one more note could break process
    death for every user, so they are loaded fields: visible in the row count,
    absent from the bytes the host keeps.
    """
    host = Host(app, repo=a_store([(n, f"Note {n}") for n in range(50)]))

    assert set(data(host.snapshot())) == {"aboutOpen", "previews", "listing"}
    assert len(saved(host)) < 200
    # Fifty rows render; none of them are in what the host saves.
    assert "Note 49" in [props["text"] for props in nodes(host.snapshot(), "Text")]
    assert len(host.repo.load()) == 50


def test_ten_thousand_notes_survive_a_restart_without_the_bundle_complaining(
    app: ModuleType,
    tmp_path: Path,
) -> None:
    """Phase 3's acceptance bar, against the real file-backed store.

    Ten thousand notes do not fit in a Bundle, and the exception that says so
    names nothing useful -- so the notes live on disk and the saved stack holds
    only what each screen needs to come back.
    """
    from notes_app.data.notes_repo import FileNotesRepo
    from notes_app.domain.models import Note

    use_root(tmp_path)
    try:
        # Seed the store directly: ten thousand taps through the bridge would be
        # a test of the bridge, not of the seam this is about.
        FileNotesRepo().store(
            [Note(index, f"Note {index}", "x" * 200) for index in range(10_000)]
        )

        host = Host(app, route=editor(1), repo=FileNotesRepo())
        assert len(host.repo.load()) == 10_000
        assert held_of(host, 9_999).title == "Note 9999"
        assert set(data(host.snapshot())) == {"noteId", "titleCaret", "bodyCaret"}
        assert len(saved(host)) < 400
        # The file, meanwhile, is megabytes -- which is exactly why it is there.
        assert (tmp_path / "notes.json").stat().st_size > 1_000_000

        # A second process, reading the same files.
        restarted = Host(
            app, route=editor(1), restore=saved(host), repo=FileNotesRepo()
        )
        assert stack(restarted.snapshot()) == ["NotesRoute", "EditorRoute"]
        assert len(restarted.repo.load()) == 10_000
    finally:
        use_root(Path.cwd())


def test_the_saved_stack_is_restorable_on_its_own(app: ModuleType) -> None:
    host = Host(app)
    host.tap("SetPreviews", value=False)
    host.tap("OpenNote", {"note_id": 2})

    # The saved stack is enough to come back on the same screens; the notes
    # come back from the app's own data.
    rebuilt = Host(app, route=editor(2), restore=saved(host))
    assert stack(rebuilt.snapshot()) == ["NotesRoute", "EditorRoute"]
    assert (
        rebuilt.snapshot()["metadata"]["data"]["stack"][0]["state"]["previews"] is False
    )
    assert titles_of(rebuilt) == host.titles


def test_every_snapshot_is_a_valid_canonical_ir(app: ModuleType) -> None:
    host = Host(app)
    host.tap("NewNote")
    host.tap("SetTitle", value="Check")
    host.tap("LeaveEditor")
    snapshot = host.snapshot()
    assert snapshot["schemaVersion"] == SCHEMA_VERSION
    assert "metadata" in snapshot
    assert host.error == ""


def test_an_action_cannot_reach_a_note_it_was_not_bound_to(app: ModuleType) -> None:
    host = Host(app)
    host.tap("OpenNote", {"note_id": 1})

    # note_id is a bound value, so an event may not supply one: the editor's own
    # binding must not be steerable at another note from outside.
    host.tap("SetTitle", noteId=2, value="hijack")
    assert host.error != ""
    assert host.titles == ["Try it", "Welcome"]

    # A field drawn for another note is harmless rather than destructive.
    host.tap("LeaveEditor")
    host.tap("OpenNote", {"note_id": 2})
    stale = {"intent": host.intent_for("SetTitle", None)["intent"]}
    host.lifecycle(stale["intent"], noteId=1, value="hijack")
    assert held_of(host, 1).title == "Welcome"


def test_every_published_intent_names_a_defined_intent(app: ModuleType) -> None:
    snapshot = Host(app).snapshot()
    contracts = (snapshot.get("metadata") or {})["intents"]
    assert contracts
    for intent in live_intents(snapshot):
        assert intent_class(intent["intent"]) is not None, intent
        assert intent["intent"] in contracts, intent


def test_the_runtime_starts_this_app_and_its_intents_work() -> None:
    """Drive the app through the real session entry point the host calls."""
    with AppDriver(APP.parent) as driver:
        assert driver.snapshot()["root"]["type"] == "Scaffold"
        driver.click(type="FloatingActionButton")
        assert stack(driver.snapshot()) == ["NotesRoute", "EditorRoute"]
        driver.lifecycle("onBackRequested")
        assert stack(driver.snapshot()) == ["NotesRoute"]
        assert driver.failures == []


def test_the_app_survives_a_hot_reload_of_a_module_inside_its_package() -> None:
    """A reload must re-import the whole package, not just the entrypoint."""
    from notes_app.data.notes_repo import FileNotesRepo
    from notes_app.domain.models import Note

    sys.path.insert(0, str(APP))
    screen = APP / "notes_app" / "views" / "list_screen.py"
    original = screen.read_text()
    cached = APP / "notes_app" / "__pycache__"
    # The session builds the real container, so point storage somewhere a test
    # may write. Otherwise this would leave a notes.json in the repository.
    use_root(Path(tempfile.mkdtemp()))
    FileNotesRepo().store([Note(*held) for held in SEEDED])
    failures: list[str] = []
    loop = LoopThread(lambda scope, error: failures.append(f"{scope}: {error}"))
    try:
        session = loop.call(lambda: RuntimeSession("main:app", "", debug=True))

        def texts() -> list[str]:
            snapshot = json.loads(loop.call(session.snapshot))
            return [props["text"] for props in nodes(snapshot, "Text")]

        assert "Notes" in texts()

        # A different length on purpose. A same-length edit restores to a file
        # whose mtime and size match what Python cached before the test, and it
        # will go on using the stale bytecode -- which would make this test pass
        # for entirely the wrong reason.
        screen.write_text(original.replace('text="Notes"', 'text="Reloaded heading"'))
        loop.call(session.reload, "")

        assert loop.call(session.error) == ""
        assert "Reloaded heading" in texts()

        # The intents have to resolve too, or every control is inert.
        intent = next(
            intent
            for intent in live_intents(json.loads(loop.call(session.snapshot)))
            if intent["intent"].endswith(".NewNote")
        )
        loop.call(session.accept_action, json.dumps({**intent, "payload": {}}))
        assert loop.call(session.error) == ""
        assert "Title" in [
            props.get("label")
            for props in nodes(json.loads(loop.call(session.snapshot)), "TextField")
        ]
        loop.call(session.close)
        assert failures == []
    finally:
        loop.stop()
        screen.write_text(original)
        shutil.rmtree(cached, ignore_errors=True)
        sys.path.remove(str(APP))
        use_root(Path.cwd())
