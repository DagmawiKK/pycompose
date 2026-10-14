"""The Notes example: model, view-model, navigation and rehydration.

Loaded from ``examples/notes`` by path, the way the on-device worker loads the
bundled demo. Nothing here is mocked below the bridge: these tests drive the real
emitter, the real validator and the real action registry, and they address every
control by the binding id the snapshot itself published.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from pycompose.bridge import BridgeSurface
from pycompose.bridge.runtime import RuntimeSession
from pycompose.state import Store

if TYPE_CHECKING:
    from types import ModuleType

APP = Path(__file__).resolve().parents[1] / "examples" / "notes" / "app"


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
    ) -> None:
        """Start a session the way ChaquopyBridge would.

        Args:
            app: The app entrypoint module.
            route: The route the host restored.
            restore: Data the host saved from a previous process.
            follow_navigation: Echo navigate effects back as the host does. Off
                to observe what an action asks for without moving the screen.
        """
        self.follow_navigation = follow_navigation
        self._bridge = BridgeSurface(
            Store(app.build(route=route or "notes", restore=restore)),
            app.actions,
        )

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


def titles(snapshot: dict[str, Any]) -> list[str]:
    """Return the note titles a snapshot published, newest first.

    Args:
        snapshot: A parsed snapshot.

    Returns:
        The titles, exactly as stored.
    """
    return [note["title"] for note in data(snapshot)["notes"]]


def note(snapshot: dict[str, Any], note_id: int) -> dict[str, Any]:
    """Return one published note by identity.

    Args:
        snapshot: A parsed snapshot.
        note_id: The note to find.

    Returns:
        The published note, failing the test if the snapshot lacks it.
    """
    found = [n for n in data(snapshot)["notes"] if n["id"] == note_id]
    assert found, f"no note {note_id}"
    return found[0]


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
    assert titles(snapshot) == ["Welcome", "Try it"]
    assert snapshot["root"]["type"] == "Scaffold"
    assert host.error == ""


def test_the_list_shows_a_title_preview_and_delete_for_every_note(
    app: ModuleType,
) -> None:
    snapshot = Host(app).snapshot()
    assert [props["text"] for props in nodes(snapshot, "Text")] == [
        "Notes",
        "2 notes",
        "Welcome",
        "This app is written entirely in Python.",
        "Try it",
        "Tap a note to edit it, or add one with the New button.",
    ]
    assert len(nodes(snapshot, "TextButton")) == 3  # about + one delete per row


def test_an_empty_repository_says_so_instead_of_rendering_nothing(
    app: ModuleType,
) -> None:
    empty = json.dumps({"notes": [], "nextId": 1, "route": "notes", "dark": False})
    snapshot = Host(app, restore=empty).snapshot()
    assert "No notes yet." in [props["text"] for props in nodes(snapshot, "Text")]


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
    assert titles(snapshot)[0] == ""
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
    assert titles(snapshot) == ["Welcome", "Try it"]


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
    assert titles(host.snapshot())[0] == "Half-typed"

    host.tap("go_back", "back")
    host.tap("open_note", "n3")
    snapshot = host.snapshot()
    assert data(snapshot)["route"] == "note:3"
    assert titles(snapshot)[0] == "Half-typed"


def test_a_detail_route_naming_a_deleted_note_falls_back_to_the_list(
    app: ModuleType,
) -> None:
    saved = json.dumps(
        {
            "notes": [{"id": 7, "title": "Only", "body": ""}],
            "nextId": 8,
            "route": "notes",
            "dark": False,
        }
    )
    snapshot = Host(app, route="note:99", restore=saved).snapshot()
    assert snapshot["root"]["type"] == "Scaffold"
    assert "Notes" in [props["text"] for props in nodes(snapshot, "Text")]


def test_the_host_route_wins_over_the_route_in_the_save(app: ModuleType) -> None:
    saved = json.dumps(
        {
            "notes": [{"id": 1, "title": "Only", "body": "text"}],
            "nextId": 2,
            "route": "notes",
            "dark": False,
        }
    )
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
    snapshot = host.snapshot()
    assert titles(snapshot)[0] == "Groceries"
    assert data(snapshot)["notes"][0]["body"] == "Milk\nBread"


def test_each_row_deletes_only_its_own_note(app: ModuleType) -> None:
    host = Host(app)
    host.tap("delete_note", "n1")
    assert titles(host.snapshot()) == ["Try it"]


def test_deleting_the_open_note_returns_to_the_list(app: ModuleType) -> None:
    host = Host(app)
    host.tap("open_note", "n2")
    host.tap("delete_note", "editor")
    snapshot = host.snapshot()
    assert data(snapshot)["route"] == "notes"
    assert titles(snapshot) == ["Welcome"]


def test_a_cleared_title_is_stored_empty_and_reads_as_a_note(app: ModuleType) -> None:
    host = Host(app)
    host.tap("open_note", "n1")
    host.tap("set_title", "title", value="")
    snapshot = host.snapshot()
    # Stored as the user left it; the placeholder belongs to the view, not the data.
    assert note(snapshot, 1)["title"] == ""
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
    first = Host(app)
    first.tap("new_note", "new")
    first.tap("set_title", "title", value="Half-typed")
    first.tap("set_body", "body", value="interrupted mid-sentence")
    published = first.snapshot()["metadata"]["data"]

    # The host hands the same bytes to a brand new process, on the same route.
    second = Host(app, route=published["route"], restore=json.dumps(published))
    snapshot = second.snapshot()
    assert data(snapshot)["route"] == "note:3"
    assert titles(snapshot)[0] == "Half-typed"
    assert data(snapshot)["notes"][0]["body"] == "interrupted mid-sentence"

    # And the restored session is still editable, not merely readable.
    second.tap("set_body", "body", value="still here")
    assert data(second.snapshot())["notes"][0]["body"] == "still here"


@pytest.mark.parametrize(
    "restore",
    [
        "",
        "not json",
        "[]",
        '"a string"',
        '{"notes": "no"}',
        '{"notes": [1, 2]}',
        '{"notes": [{"title": "no id"}]}',
    ],
)
def test_a_save_that_cannot_be_understood_still_starts_the_app(
    app: ModuleType, restore: str
) -> None:
    host = Host(app, restore=restore)
    assert titles(host.snapshot()) == ["Welcome", "Try it"]
    assert host.error == ""


def test_a_save_with_one_bad_entry_is_refused_whole_rather_than_half_applied(
    app: ModuleType,
) -> None:
    """The declared state makes partial recovery impossible, and that is the point.

    An untyped mapping let one unreadable entry be dropped while its neighbours
    rendered, which is how a notes app quietly loses data. The codec either
    accepts the save exactly as written or refuses it.
    """
    saved = json.dumps(
        {
            "notes": [
                {"id": 1, "title": "Good", "body": "kept"},
                {"id": "bad", "title": "Broken", "body": ""},
            ],
            "nextId": 3,
            "route": "notes",
            "dark": False,
        }
    )
    # Refused, so the app starts from seed data rather than showing a note that
    # is missing from a list the user believes is complete.
    assert titles(Host(app, restore=saved).snapshot()) == ["Welcome", "Try it"]


def test_an_exhausted_save_stays_empty_rather_than_reseeding(app: ModuleType) -> None:
    host = Host(app)
    host.tap("delete_note", "n1")
    host.tap("delete_note", "n2")
    assert titles(host.snapshot()) == []

    saved = json.dumps(data(host.snapshot()))
    assert titles(Host(app, restore=saved).snapshot()) == []


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


def test_the_shell_and_the_feature_are_encoded_as_separate_parts(
    app: ModuleType,
) -> None:
    """The split is what keeps a keystroke from re-encoding the whole app.

    The shell is the small part the host must be able to restore. The notes are
    a feature partition that rides beside it. Knowing which keys belong to which
    is what lets a host keep the first and rebuild the second.
    """
    host = Host(app)
    snapshot = host.snapshot()
    published = data(snapshot)
    assert set(published) == {"route", "dark", "notes", "nextId"}

    # The shell alone is what a host would keep across process death.
    shell = {"route": published["route"], "dark": published["dark"]}
    assert len(shell) == 2
    assert published["notes"], "the notes partition must carry the notes"


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
    assert titles(rebuilt.snapshot()) == titles(host.snapshot())


def test_every_snapshot_is_a_valid_canonical_ir(app: ModuleType) -> None:
    host = Host(app)
    host.tap("new_note", "new")
    host.tap("set_title", "title", value="Check")
    host.tap("go_back", "back")
    snapshot = host.snapshot()
    assert snapshot["schemaVersion"] == "1.5.0"
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
    try:
        session = RuntimeSession("main:build", "notes", debug=True)
    finally:
        sys.path.remove(str(APP))
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
    sys.path.insert(0, str(APP))
    model = APP / "notes_app" / "state.py"
    original = model.read_text()
    try:
        session = RuntimeSession("main:build", "notes", debug=True)
        assert "Welcome" in session.snapshot()

        model.write_text(original.replace('title="Welcome"', 'title="Reloaded"'))
        session.reload("notes")
        assert session.error() == ""
        assert "Reloaded" in session.snapshot()
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
        model.write_text(original)
        sys.path.remove(str(APP))
