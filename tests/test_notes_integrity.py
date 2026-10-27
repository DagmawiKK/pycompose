"""Integrity, rehydration, size and hot-reload behaviour of the notes example."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from pycompose.bridge.runtime import RuntimeSession
from pycompose.ir.generated_validators import SCHEMA_VERSION
from pycompose.repository import use_root

if TYPE_CHECKING:
    from types import ModuleType

from notes_support import (
    APP,
    SEEDED,
    Host,
    a_store,
    data,
    held_of,
    load_notes_app,
    nodes,
    titles_of,
)


@pytest.fixture(scope="module")
def app() -> ModuleType:
    """Import the Notes app exactly as the Android worker does."""
    return load_notes_app()


def test_an_emptied_store_stays_empty_rather_than_reseeding(
    app: ModuleType,
) -> None:
    """Deleting everything is a decision, not a state the app recovers from."""
    disk = a_store()
    host = Host(app, repo=disk)
    host.tap("delete_note", {"note_id": 1})
    host.tap("delete_note", {"note_id": 2})
    assert host.titles == []

    saved = json.dumps(data(host.snapshot()))
    assert titles_of(Host(app, repo=disk, restore=saved)) == []


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


def test_only_the_shell_crosses_the_boundary(app: ModuleType) -> None:
    """The whole point of Phase 3: the Bundle carries the shell and nothing else.

    Anything the host saves has to fit in a transaction buffer measured in
    kilobytes. Publishing the notes here would mean one more note could break
    process death for every user, so the published data stays a shell and the
    notes stay in the repository -- visible in the row count, absent from the
    bytes the host keeps.
    """
    host = Host(app, repo=a_store([(n, f"Note {n}") for n in range(50)]))
    published = data(host.snapshot())

    assert set(published) == {
        "route",
        "titleCaret",
        "bodyCaret",
        "aboutOpen",
        "previews",
        "listing",
    }
    assert len(json.dumps(published)) < 200
    # Fifty rows render; none of them are in what the host saves.
    assert "Note 49" in [props["text"] for props in nodes(host.snapshot(), "Text")]
    assert len(host.repo.load()) == 50


def test_ten_thousand_notes_survive_a_restart_without_the_bundle_complaining(
    app: ModuleType,
    tmp_path: Path,
) -> None:
    """Phase 3's acceptance bar, against the real file-backed store.

    Before this seam every note travelled through ``SavedStateHandle``. Ten
    thousand of them do not fit in a Bundle, and the exception that says so
    names nothing useful -- so the notes went to disk and the shell stayed.

    Opened on the editor rather than the list, and that is not a dodge: the list
    expands every row into the snapshot, which has its own ceiling. Removing the
    Bundle limit moved the wall rather than abolishing it, and pagination is
    what the list still needs before ten thousand rows can be shown.
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

        host = Host(app, route="note:1", repo=FileNotesRepo())
        published = data(host.snapshot())
        assert len(host.repo.load()) == 10_000
        assert held_of(host, 9_999).title == "Note 9999"
        assert set(published) == {
            "route",
            "titleCaret",
            "bodyCaret",
            "aboutOpen",
            "previews",
            "listing",
        }
        assert len(json.dumps(published)) < 200
        # The file, meanwhile, is megabytes -- which is exactly why it is there.
        assert (tmp_path / "notes.json").stat().st_size > 1_000_000

        # A second process, reading the same files.
        restarted = Host(app, route="note:1", repo=FileNotesRepo())
        assert len(restarted.repo.load()) == 10_000
    finally:
        use_root(Path.cwd())


def test_the_shell_is_restorable_on_its_own(app: ModuleType) -> None:
    host = Host(app)
    published = data(host.snapshot())
    host.lifecycle("onRouteChanged", route="note:2")
    published = data(host.snapshot())

    # Restoring only the shell is enough to come back on the same screen; the
    # notes come back from the app's own data.
    rebuilt = Host(
        app,
        route=published["route"],
        restore=json.dumps(published),
    )
    assert data(rebuilt.snapshot())["route"] == "note:2"
    assert titles_of(rebuilt) == host.titles


def test_every_snapshot_is_a_valid_canonical_ir(app: ModuleType) -> None:
    host = Host(app)
    host.tap("new_note")
    host.tap("set_title", value="Check")
    host.tap("go_back")
    snapshot = host.snapshot()
    assert snapshot["schemaVersion"] == SCHEMA_VERSION
    assert "metadata" in snapshot
    assert host.error == ""


def test_an_action_cannot_reach_a_note_it_was_not_bound_to(app: ModuleType) -> None:
    host = Host(app)
    host.tap("open_note", {"note_id": 1})
    before = host.snapshot()

    # note_id is a bound value, so an event may not supply one: the editor's own
    # binding must not be steerable at another note from outside.
    host._bridge.accept_action(
        json.dumps(
            {
                "actionId": host._id_for("set_title", None),
                "payload": {"note_id": 2, "value": "hijack"},
            }
        )
    )
    assert host.error != ""
    assert data(host.snapshot()) == data(before)


def test_every_published_binding_names_a_registered_handler(app: ModuleType) -> None:
    snapshot = Host(app).snapshot()
    bindings = (snapshot.get("metadata") or {})["actionBindings"]
    registered = set(app.actions.handlers())
    assert bindings
    for binding_id, spec in bindings.items():
        assert spec["handlerId"] in registered, binding_id


def test_the_runtime_starts_this_app_and_its_actions_work() -> None:
    """Drive the app through the real session entry point the host calls.

    This is the one that matters most and is easiest to get wrong: the runtime
    discovers an app's registry by the module-level name ``actions``. Export it
    under any other spelling and the registry comes up empty, every published
    binding fails validation, and the app starts to a blank screen.
    """
    sys.path.insert(0, str(APP))
    # The real session builds the app's real container, so storage has to point
    # somewhere a test may write rather than at the repository working directory.
    scratch = Path(tempfile.mkdtemp())
    use_root(scratch)
    try:
        session = RuntimeSession("main:app", "notes", debug=True)
    finally:
        sys.path.remove(str(APP))
        sys.modules.pop("main", None)
        use_root(Path.cwd())
    assert session.error() == ""
    snapshot = json.loads(session.snapshot())
    assert snapshot["root"]["type"] == "Scaffold"

    session.accept_action(
        json.dumps(
            {
                "actionId": next(
                    key
                    for key in snapshot["metadata"]["actionBindings"]
                    if key.endswith(".new_note")
                ),
                "payload": {},
            }
        )
    )
    assert session.error() == ""
    # Navigation is requested, then the host echoes the destination back.
    assert json.loads(session.snapshot())["metadata"]["data"]["route"] == "notes"
    session.accept_action(
        json.dumps({"actionId": "onRouteChanged", "payload": {"route": "note:3"}})
    )
    assert session.error() == ""
    assert json.loads(session.snapshot())["metadata"]["data"]["route"] == "note:3"


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
    try:
        session = RuntimeSession("main:app", "notes", debug=True)
        assert "Notes" in [
            props["text"] for props in nodes(json.loads(session.snapshot()), "Text")
        ]

        # A different length on purpose. A same-length edit restores to a file
        # whose mtime and size match what Python cached before the test, and it
        # will go on using the stale bytecode -- which would make this test pass
        # for entirely the wrong reason.
        screen.write_text(original.replace('text="Notes"', 'text="Reloaded heading"'))
        session.reload("notes")

        assert session.error() == ""
        assert "Reloaded heading" in [
            props["text"] for props in nodes(json.loads(session.snapshot()), "Text")
        ]

        # The registry has to come back too, or every control is inert.
        session.accept_action(
            json.dumps(
                {
                    "actionId": next(
                        key
                        for key in json.loads(session.snapshot())["metadata"][
                            "actionBindings"
                        ]
                        if key.endswith(".new_note")
                    ),
                    "payload": {},
                }
            )
        )
        assert session.error() == ""
    finally:
        screen.write_text(original)
        shutil.rmtree(cached, ignore_errors=True)
        sys.path.remove(str(APP))
