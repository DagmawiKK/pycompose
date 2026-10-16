"""The Notes example: model, view-model, navigation and rehydration.

Loaded from ``examples/notes`` by path, the way the on-device worker loads the
bundled demo. Nothing here is mocked below the bridge: these tests drive the real
emitter, the real validator and the real action registry, and they address every
control by the binding id the snapshot itself published.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from pycompose import AppContext, install_context
from pycompose.bridge import BridgeSurface
from pycompose.bridge.runtime import RuntimeSession
from pycompose.repository import use_root
from pycompose.state import Store

if TYPE_CHECKING:
    from types import ModuleType

APP = Path(__file__).resolve().parents[1] / "examples" / "notes" / "app"


SEEDED = [
    (1, "Welcome", "This app is written entirely in Python."),
    (2, "Try it", "Tap a note to edit it, or add one with the New button."),
]


def a_store(notes: Any = ...) -> Any:
    """Return an in-memory store, seeded unless told otherwise.

    Args:
        notes: What it should hold. Defaults to the two seeded notes; pass a list
            for an exact inventory.

    Returns:
        A memory-backed note repository.
    """
    from notes_app.data.notes_repo import MemoryNotesRepo
    from notes_app.domain.models import Note

    return MemoryNotesRepo(
        [Note(*held) for held in (SEEDED if notes is ... else notes)]
    )


@pytest.fixture(scope="module")
def app() -> ModuleType:
    """Import the Notes app exactly as the Android worker does.

    Returns:
        The app package's entrypoint module.
    """
    sys.path.insert(0, str(APP))
    try:
        import main as notes

        return notes
    finally:
        sys.path.remove(str(APP))


class Host:
    """A stand-in for the Android host: starts a session and feeds it actions."""

    def __init__(
        self,
        app: ModuleType,
        *,
        route: str = "",
        restore: str = "",
        follow_navigation: bool = True,
        repo: Any = None,
    ) -> None:
        """Start a session the way ChaquopyBridge would.

        Args:
            app: The app entrypoint module.
            route: The route the host restored.
            restore: Data the host saved from a previous process.
            follow_navigation: Echo navigate effects back as the host does. Off
                to observe what an action asks for without moving the screen.
            repo: Where the notes live. Defaults to an in-memory store, so no test
                touches a file and the data layer is never on the path.
        """
        from notes_app.container import AppContainer
        from notes_app.domain import Notes

        self.follow_navigation = follow_navigation
        self.repo: Any = repo if repo is not None else a_store()
        self.container = AppContainer(Notes(self.repo))
        # A real session installs both of these while resolving the app's
        # factory. A test driving the surface directly stands in for it, so it
        # says so once, in one place.
        app.actions.install_container(self.container)
        install_context(
            AppContext(
                actions=app.actions,
                container=self.container,
                notes=self.container.notes,
            )
        )
        self._bridge = BridgeSurface(
            Store(
                app.build(
                    route=route or "notes",
                    restore=restore,
                    container=self.container,
                )
            ),
            app.actions,
        )

    @property
    def titles(self) -> list[str]:
        """Return the note titles held, newest first.

        Returns:
            Every stored title.
        """
        return [
            held.title
            for held in sorted(self.repo.load(), key=lambda n: n.id, reverse=True)
        ]

    def title_of(self, note_id: int) -> str:
        """Return one note's stored title.

        Args:
            note_id: Identity to look for.

        Returns:
            The stored title.

        Raises:
            AssertionError: If no such note is held.
        """
        for held in self.repo.load():
            if held.id == note_id:
                return held.title
        raise AssertionError(f"no held note with id {note_id}")

    @property
    def error(self) -> str:
        """Return the worker's last diagnostic.

        Returns:
            The error text, or an empty string.
        """
        return self._bridge.expose_latest_error() or ""

    def snapshot(self) -> dict[str, Any]:
        """Return the latest snapshot, failing loudly if there is none.

        Returns:
            The parsed snapshot.
        """
        source = self._bridge.expose_latest_snapshot()
        assert source is not None, self.error
        return json.loads(source)

    def tap(self, handler: str, instance: str = "", **event: Any) -> None:
        """Deliver one action envelope addressed by handler and instance.

        Args:
            handler: The action's function name.
            instance: The bind instance naming this control.
            **event: Event fields the handler declares as unfilled.
        """
        self._bridge.accept_action(
            json.dumps({"actionId": self._id_for(handler, instance), "payload": event})
        )
        self._follow_navigation()

    def lifecycle(self, event: str, **payload: Any) -> None:
        """Deliver one host lifecycle event by its camelCase name.

        Args:
            event: The lifecycle event name.
            **payload: Fields the event declares.
        """
        self._bridge.accept_action(json.dumps({"actionId": event, "payload": payload}))
        self._follow_navigation()

    def follow(self, destination: str) -> None:
        """Honour a navigate effect the way the host does.

        The host no longer rebuilds Python for a route change. It echoes the new
        route back as an ordinary lifecycle action and lets the app decide what
        that route means.

        Args:
            destination: The route carried by the snapshot's navigate effect.
        """
        self.lifecycle("onRouteChanged", route=destination)

    def _follow_navigation(self) -> None:
        """Echo any requested navigation, exactly as the host would."""
        if not self.follow_navigation:
            return
        for kind, body in effects(self.snapshot()):
            if kind == "navigate":
                self.lifecycle("onRouteChanged", **body)

    def _id_for(self, handler: str, instance: str) -> str:
        """Return the binding id a control was given in the current snapshot.

        Args:
            handler: The action's function name.
            instance: The bind instance for this control.

        Returns:
            The binding id.

        Raises:
            AssertionError: If no live binding matches.
        """
        bindings = (self.snapshot().get("metadata") or {}).get("actionBindings", {})
        suffix = f".{handler}.{instance}"
        for binding_id in bindings:
            if binding_id.endswith(suffix):
                return binding_id
        raise AssertionError(f"no live binding for {handler}.{instance}")


def data(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return the app data a snapshot published.

    Args:
        snapshot: A parsed snapshot.

    Returns:
        The published data.
    """
    return snapshot["metadata"]["data"]


def titles_of(host: Any) -> list[str]:
    """Return the titles held by a host started in one expression.

    Args:
        host: The host.

    Returns:
        Every stored title, newest first.
    """
    return host.titles


def held_of(host: Any, note_id: int) -> Any:
    """Return one stored note by identity.

    Args:
        host: The running host.
        note_id: The note to find.

    Returns:
        The stored note.

    Raises:
        AssertionError: If no such note is held.
    """
    for held in host.repo.load():
        if held.id == note_id:
            return held
    raise AssertionError(f"no held note {note_id}")


def effects(snapshot: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Return the effects a snapshot asked the host to run, in order.

    Args:
        snapshot: A parsed snapshot.

    Returns:
        Each effect's kind and payload.
    """
    return [
        (effect["kind"], effect.get("payload", {}))
        for effect in (snapshot.get("metadata") or {}).get("effects", [])
    ]


def nodes(snapshot: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """Return the props of every node of one component type.

    Args:
        snapshot: A parsed snapshot.
        kind: The component type to collect.

    Returns:
        Each matching node's props, in tree order.
    """
    found: list[dict[str, Any]] = []
    pending = [snapshot["root"]]
    while pending:
        node = pending.pop(0)
        if node["type"] == kind:
            found.append(node["props"])
        pending = node.get("children", []) + pending
    return found


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------


def test_a_fresh_install_opens_on_the_list(app: ModuleType) -> None:
    host = Host(app)
    snapshot = host.snapshot()
    assert data(snapshot)["route"] == "notes"
    # Newest first, so the most recent note is the one under the thumb.
    assert host.titles == ["Try it", "Welcome"]
    assert snapshot["root"]["type"] == "Scaffold"
    assert host.error == ""


def test_a_genuinely_empty_store_opens_empty_rather_than_seeding(
    app: ModuleType,
) -> None:
    """Nothing invents notes. A real install starts empty and stays that way."""
    host = Host(app, repo=a_store([]))
    assert host.titles == []
    assert "No notes yet." in [
        props["text"] for props in nodes(host.snapshot(), "Text")
    ]


def test_the_list_shows_a_title_preview_and_delete_for_every_note(
    app: ModuleType,
) -> None:
    snapshot = Host(app).snapshot()
    assert [props["text"] for props in nodes(snapshot, "Text")] == [
        "Notes",
        "2 notes",
        "Try it",
        "Tap a note to edit it, or add one with the New button.",
        "Welcome",
        "This app is written entirely in Python.",
        "How this works",
        "Every control here is native Material 3. Python states whether this "
        "sheet is open; the host drives it and reports back what it settled on.",
    ]
    # about + one delete per row + the sheet's close control
    assert len(nodes(snapshot, "TextButton")) == 4


def test_an_empty_repository_says_so_instead_of_rendering_nothing(
    app: ModuleType,
) -> None:
    snapshot = Host(app, repo=a_store([])).snapshot()
    assert "No notes yet." in [props["text"] for props in nodes(snapshot, "Text")]


def test_the_about_sheet_opens_and_closes_through_one_transition(
    app: ModuleType,
) -> None:
    """One handler serves the button, the close control and the sheet's report.

    A dismissal the app did not cause arrives through the sheet's own
    ``onOpenChange``, so the app assigns the value it was handed rather than
    toggling what it believed. That is what keeps a report from fighting a
    user's swipe, and it is the same transition either way.
    """
    host = Host(app)
    assert data(host.snapshot())["aboutOpen"] is False

    # The button states the value it wants, so the binding carries it.
    host.tap("set_about", "about")
    snapshot = host.snapshot()
    assert data(snapshot)["aboutOpen"] is True
    assert nodes(snapshot, "ModalBottomSheet")[0]["open"] is True

    # What the host sends once the sheet has settled: the user dismissed it.
    # This binding names no value, so the event is the one carrying it.
    host.tap("set_about", "about_sheet", open=False)
    assert data(host.snapshot())["aboutOpen"] is False

    host.tap("set_about", "about_close")
    assert data(host.snapshot())["aboutOpen"] is False


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------


def test_creating_a_note_requests_navigation_rather_than_moving_itself(
    app: ModuleType,
) -> None:
    """The app asks; the host decides. Nothing here relocates the screen alone."""
    host = Host(app, follow_navigation=False)
    host.tap("new_note", "new")
    snapshot = host.snapshot()

    # The note exists and a move is requested, but the screen has not moved.
    assert host.titles[0] == ""
    assert data(snapshot)["route"] == "notes"
    assert effects(snapshot) == [("haptic", {}), ("navigate", {"route": "note:3"})]

    # The host honours the request, and now the screen moves.
    host.follow("note:3")
    after = host.snapshot()
    assert data(after)["route"] == "note:3"
    # Effects are one-shot: the echo does not replay the navigation.
    assert effects(after) == []


def test_a_route_this_app_does_not_know_leaves_the_screen_where_it_was(
    app: ModuleType,
) -> None:
    host = Host(app, follow_navigation=False)
    host.tap("new_note", "new")
    host.follow("somewhere/unknown")
    assert data(host.snapshot())["route"] == "notes"


def test_opening_and_leaving_a_note_round_trips(app: ModuleType) -> None:
    host = Host(app)
    host.tap("open_note", "n1")
    assert data(host.snapshot())["route"] == "note:1"

    host.tap("go_back", "back")
    snapshot = host.snapshot()
    assert data(snapshot)["route"] == "notes"
    assert host.titles == ["Try it", "Welcome"]


def test_system_back_leaves_the_editor_and_closes_the_app_from_the_list(
    app: ModuleType,
) -> None:
    host = Host(app)
    host.tap("open_note", "n1")
    host.lifecycle("onBackRequested")
    assert data(host.snapshot())["route"] == "notes"

    host.lifecycle("onBackRequested")
    assert effects(host.snapshot()) == [("finish", {})]


def test_a_route_change_never_rebuilds_the_session(app: ModuleType) -> None:
    """Navigation is a state transition, not a process restart.

    This is what makes a view-model retainable: everything the user typed before
    the screen changed is still here afterwards, because nothing was thrown away.
    """
    host = Host(app)
    host.tap("new_note", "new")
    host.tap("set_title", "title", value="Half-typed")
    assert host.titles[0] == "Half-typed"

    host.tap("go_back", "back")
    host.tap("open_note", "n3")
    snapshot = host.snapshot()
    assert data(snapshot)["route"] == "note:3"
    assert host.titles[0] == "Half-typed"


def test_a_detail_route_naming_a_deleted_note_falls_back_to_the_list(
    app: ModuleType,
) -> None:
    snapshot = Host(app, route="note:99", repo=a_store([(7, "Only")])).snapshot()
    assert snapshot["root"]["type"] == "Scaffold"
    assert "Notes" in [props["text"] for props in nodes(snapshot, "Text")]


def test_the_host_route_wins_over_the_route_in_the_save(app: ModuleType) -> None:
    saved = json.dumps({"route": "notes", "dark": False})
    assert (
        data(Host(app, route="note:1", restore=saved).snapshot())["route"] == "note:1"
    )


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


def test_typing_updates_the_note_being_edited(app: ModuleType) -> None:
    host = Host(app)
    host.tap("new_note", "new")
    host.tap("set_title", "title", value="Groceries")
    host.tap("set_body", "body", value="Milk\nBread")
    assert host.titles[0] == "Groceries"
    assert held_of(host, 3).body == "Milk\nBread"

    # The list describes its own size, from a rule in the domain rather than
    # from whatever state happened to be carrying the notes.
    host.tap("go_back", "back")
    assert "3 notes" in [props["text"] for props in nodes(host.snapshot(), "Text")]


def test_each_row_deletes_only_its_own_note(app: ModuleType) -> None:
    host = Host(app)
    host.tap("delete_note", "n1")
    assert host.titles == ["Try it"]


def test_deleting_the_open_note_returns_to_the_list(app: ModuleType) -> None:
    host = Host(app)
    host.tap("open_note", "n2")
    host.tap("delete_note", "editor")
    snapshot = host.snapshot()
    assert data(snapshot)["route"] == "notes"
    assert host.titles == ["Welcome"]


def test_a_cleared_title_is_stored_empty_and_reads_as_a_note(app: ModuleType) -> None:
    host = Host(app)
    host.tap("open_note", "n1")
    host.tap("set_title", "title", value="")
    snapshot = host.snapshot()
    # Stored as the user left it; the placeholder belongs to the view, not the data.
    assert held_of(host, 1).title == ""
    assert "Untitled" in [props["text"] for props in nodes(snapshot, "Text")]


def test_an_empty_body_previews_itself_clearly(app: ModuleType) -> None:
    host = Host(app)
    host.tap("open_note", "n1")
    host.tap("set_body", "body", value="   ")
    host.tap("go_back", "back")
    texts = [props["text"] for props in nodes(host.snapshot(), "Text")]
    assert "No additional text" in texts


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_half_typed_text_survives_process_death(app: ModuleType) -> None:
    """Death costs the session shell and the repository keeps the work.

    Those are two different rescues and the test needs both: the shell is what
    the host hands back, and storage is what outlives the process on its own.
    """
    disk = a_store()
    first = Host(app, repo=disk)
    first.tap("new_note", "new")
    first.tap("set_title", "title", value="Half-typed")
    first.tap("set_body", "body", value="interrupted mid-sentence")
    published = first.snapshot()["metadata"]["data"]

    # A brand new process, same storage, and the bytes the host kept.
    second = Host(
        app, repo=disk, route=published["route"], restore=json.dumps(published)
    )
    snapshot = second.snapshot()
    assert data(snapshot)["route"] == "note:3"
    assert second.titles[0] == "Half-typed"
    assert held_of(second, 3).body == "interrupted mid-sentence"

    # And the restored session is still editable, not merely readable.
    second.tap("set_body", "body", value="still here")
    assert held_of(second, 3).body == "still here"


@pytest.mark.parametrize(
    "restore",
    [
        "",
        "not json",
        "[]",
        '"a string"',
        '{"route": 7}',
        '{"route": "notes", "dark": "maybe"}',
        '{"route": "notes", "surprise": 1}',
    ],
)
def test_a_save_that_cannot_be_understood_still_starts_the_app(
    app: ModuleType, restore: str
) -> None:
    host = Host(app, restore=restore)
    assert host.titles == ["Try it", "Welcome"]
    assert host.error == ""


def test_a_shell_with_one_bad_field_is_refused_whole_rather_than_half_applied(
    app: ModuleType,
) -> None:
    """The declared shell makes partial recovery impossible, and that is the point.

    An untyped mapping let one unreadable field fall back to its default while
    its neighbours applied, so a restore silently produced a state the user never
    had. The codec either accepts the save exactly as written or refuses it.
    """
    saved = json.dumps({"route": "note:4", "dark": "not a boolean"})
    assert titles_of(Host(app, restore=saved)) == ["Try it", "Welcome"]


def test_an_emptied_store_stays_empty_rather_than_reseeding(
    app: ModuleType,
) -> None:
    """Deleting everything is a decision, not a state the app recovers from."""
    disk = a_store()
    host = Host(app, repo=disk)
    host.tap("delete_note", "n1")
    host.tap("delete_note", "n2")
    assert host.titles == []

    saved = json.dumps(data(host.snapshot()))
    assert titles_of(Host(app, repo=disk, restore=saved)) == []


# ---------------------------------------------------------------------------
# Theming
# ---------------------------------------------------------------------------


def test_dark_mode_recolours_the_screen(app: ModuleType) -> None:
    host = Host(app)
    assert host.snapshot()["root"]["props"]["containerColor"] == "#FBF9F7"
    host.lifecycle(
        "onConfigChanged",
        darkMode=True,
        orientation="portrait",
        locale="en-US",
        density=2.0,
    )
    assert host.snapshot()["root"]["props"]["containerColor"] == "#101416"


def test_the_appearance_survives_process_death(app: ModuleType) -> None:
    host = Host(app)
    host.lifecycle(
        "onConfigChanged",
        darkMode=True,
        orientation="portrait",
        locale="en-US",
        density=2.0,
    )
    saved = json.dumps(data(host.snapshot()))
    assert Host(app, restore=saved).snapshot()["root"]["props"]["containerColor"] == (
        "#101416"
    )


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


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

    assert set(published) == {"route", "dark", "titleCaret", "bodyCaret", "aboutOpen"}
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
            "dark",
            "titleCaret",
            "bodyCaret",
            "aboutOpen",
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
    host.tap("new_note", "new")
    host.tap("set_title", "title", value="Check")
    host.tap("go_back", "back")
    snapshot = host.snapshot()
    assert snapshot["schemaVersion"] == "1.20.0"
    assert "metadata" in snapshot
    assert host.error == ""


def test_an_action_cannot_reach_a_note_it_was_not_bound_to(app: ModuleType) -> None:
    host = Host(app)
    host.tap("open_note", "n1")
    before = host.snapshot()

    # note_id is a bound value, so an event may not supply one: the editor's own
    # binding must not be steerable at another note from outside.
    host._bridge.accept_action(
        json.dumps(
            {
                "actionId": host._id_for("set_title", "title"),
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
        session = RuntimeSession("main:build", "notes", debug=True)
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
                    if key.endswith(".new_note.new")
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
        session = RuntimeSession("main:build", "notes", debug=True)
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
                        if key.endswith(".new_note.new")
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
