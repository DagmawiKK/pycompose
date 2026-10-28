"""The Notes example: view models, the back stack, and process death.

Loaded from ``examples/notes`` by path, the way the on-device worker loads the
bundled demo. Nothing here is mocked below the bridge: these tests drive the real
emitter, the real validator and the real navigation session, and they address
every control by the intent the snapshot itself published.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

from notes_support import (
    Host,
    a_store,
    data,
    effects,
    held_of,
    load_notes_app,
    nodes,
    stack,
    titles_of,
)

from pycompose.app.navigation import route_key


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


def texts(host: Host) -> list[str]:
    return [props["text"] for props in nodes(host.snapshot(), "Text")]


def test_a_fresh_install_opens_on_the_list(app: ModuleType) -> None:
    host = Host(app)
    snapshot = host.snapshot()
    assert stack(snapshot) == ["NotesRoute"]
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
    assert "No notes yet." in texts(host)


def test_the_list_shows_a_title_preview_and_delete_for_every_note(
    app: ModuleType,
) -> None:
    host = Host(app)
    assert texts(host) == [
        "Notes",
        "2 notes",
        "Show note previews",
        "Try it",
        "Tap a note to edit it, or add one with the New button.",
        "Welcome",
        "This app is written entirely in Python.",
        "How this works",
        "Every control here is native Material 3. Python states whether this "
        "sheet is open; the host drives it and reports back what it settled on.",
        "That bar is Python state too: the share of your notes that have a body. "
        "The value is read during composition, so it tracks the notes you keep.",
        "All notes",
        "With text",
    ]
    # about + one delete per row + the sheet's close control
    assert len(nodes(host.snapshot(), "TextButton")) == 4


def test_the_notes_are_never_saved(app: ModuleType) -> None:
    """A thousand notes do not fit a Bundle, so the list's state leaves them out."""
    saved = data(Host(app).snapshot())
    assert "notes" not in saved
    assert saved == {"aboutOpen": False, "listing": "all", "previews": True}


def test_the_scaffolds_slots_hold_the_bar_and_the_button(app: ModuleType) -> None:
    """The wire has one place for a child; the slot says where it composes.

    A Scaffold's floating button and bottom bar are the Scaffold's own content,
    not the body's, so they arrive marked with the slot the parent declared --
    and the rule under the header is a real divider, stated in dp.
    """
    snapshot = Host(app).snapshot()
    assert {
        child["type"]: child.get("slot") for child in snapshot["root"]["children"]
    } == {
        "Column": None,
        "NavigationBar": "bottomBar",
        "FloatingActionButton": "floatingActionButton",
    }
    assert [rule["thickness"] for rule in nodes(snapshot, "HorizontalDivider")] == [1]


def test_the_previews_switch_rewrites_what_every_row_shows(app: ModuleType) -> None:
    """A control the host owns natively, with Python as the only source of truth.

    The switch reports the value it settled on, and the view model assigns what
    it was handed rather than flipping what it believed -- which is what keeps a
    report from fighting the user.
    """
    host = Host(app)
    assert data(host.snapshot())["previews"] is True
    assert [node["checked"] for node in nodes(host.snapshot(), "Switch")] == [True]

    host.tap("SetPreviews", value=False)
    snapshot = host.snapshot()
    assert data(snapshot)["previews"] is False
    assert [node["checked"] for node in nodes(snapshot, "Switch")] == [False]

    shown = texts(host)
    # The titles stay; the line of body under each one goes.
    assert "Try it" in shown
    assert "Welcome" in shown
    assert "Tap a note to edit it, or add one with the New button." not in shown
    assert "This app is written entirely in Python." not in shown


def test_the_filter_bar_narrows_the_list_without_leaving_it(app: ModuleType) -> None:
    """A navigation bar here is selection, not navigation: nothing moves.

    Each item binds the filter it stands for, so the tap carries no data; the
    rows and the count line follow the filter. A body of spaces carries no
    text, which is the same fact the about sheet's bar measures.
    """
    host = Host(app, repo=a_store([(1, "Body", "words"), (2, "Blank", "   ")]))
    assert [
        item["selected"] for item in nodes(host.snapshot(), "NavigationBarItem")
    ] == [True, False]

    host.tap("SetListing", {"value": "with_text"})
    snapshot = host.snapshot()
    assert data(snapshot)["listing"] == "with_text"
    assert stack(snapshot) == ["NotesRoute"]
    assert [item["selected"] for item in nodes(snapshot, "NavigationBarItem")] == [
        False,
        True,
    ]
    shown = texts(host)
    assert "Body" in shown
    assert "Blank" not in shown
    assert "1 note" in shown


def test_a_filter_that_matches_nothing_names_the_filter(app: ModuleType) -> None:
    """An empty list is two different facts, and the screen says which one."""
    host = Host(app, repo=a_store([(1, "Blank", "  ")]))
    assert "Blank" in texts(host)

    host.tap("SetListing", {"value": "with_text"})
    shown = texts(host)
    assert "No notes with text yet." in shown
    assert "No notes yet." not in shown


def _saved(*entries: tuple[str, dict[str, object]]) -> str:
    """Return a save naming each route class with its fields, bottom first."""
    from notes_app import routes

    return json.dumps(
        {
            "stack": [
                {
                    "route": {"fields": fields, "route": f"{routes.__name__}.{name}"},
                    "state": state,
                }
                for name, fields, state in (
                    (name, {} if name == "NotesRoute" else {"noteId": 1}, state)
                    for name, state in entries
                )
            ]
        }
    )


def test_a_listing_the_app_no_longer_knows_renders_the_whole_list(
    app: ModuleType,
) -> None:
    """A save can outlive the set of filters it was written against.

    The codec checks types, not domains, so a listing it does not recognise
    arrives here as an ordinary string; the screen shows every note rather than
    an empty screen nobody can explain.
    """
    host = Host(app, restore=_saved(("NotesRoute", {"listing": "everything"})))
    assert data(host.snapshot())["listing"] == "everything"
    shown = texts(host)
    assert "Try it" in shown
    assert "Welcome" in shown


def test_the_about_bar_states_a_share_the_host_reads(app: ModuleType) -> None:
    """A provider prop: the app states a number, never a function.

    ``LinearProgressIndicator.progress`` is pinned as ``() -> Float``, which
    Python cannot hand over. The app's side of that parameter is an ordinary
    number in the snapshot, and the host reads it during composition.
    """
    host = Host(app)
    seeded = nodes(host.snapshot(), "LinearProgressIndicator")
    assert [bar["progress"] for bar in seeded] == [1.0]

    # A note with no body yet: the share follows the notes back on the list.
    host.tap("NewNote")
    host.tap("LeaveEditor")
    stated = nodes(host.snapshot(), "LinearProgressIndicator")[0]["progress"]
    assert stated == pytest.approx(2 / 3)


def test_every_icon_names_a_pinned_glyph_the_host_resolves(app: ModuleType) -> None:
    """An icon vocabulary prop: the app names a pinned icon, never a vector.

    Every glyph on the screen comes from that vocabulary, and the controls that
    are nothing but an icon say what they are in words.
    """
    icons = nodes(Host(app).snapshot(), "Icon")
    assert [
        (icon["contentDescription"], icon["imageVector"]["name"]) for icon in icons
    ] == [
        ("About this app", "Filled.Info"),
        (None, "Filled.Home"),
        (None, "Filled.Edit"),
        ("New note", "Filled.Add"),
    ]


def test_the_about_sheet_opens_and_closes_through_one_intent(
    app: ModuleType,
) -> None:
    """One intent serves the button, the close control and the sheet's report.

    A dismissal the app did not cause arrives through the sheet's own
    ``onOpenChange``, so the app assigns the value it was handed rather than
    toggling what it believed.
    """
    host = Host(app)
    assert data(host.snapshot())["aboutOpen"] is False

    # The button states the value it wants, so the binding carries it.
    host.tap("SetAbout", {"open": True})
    snapshot = host.snapshot()
    assert data(snapshot)["aboutOpen"] is True
    assert nodes(snapshot, "ModalBottomSheet")[0]["open"] is True

    # What the host sends once the sheet has settled: the user dismissed it.
    # This binding names no value, so the event is the one carrying it.
    host.tap("SetAbout", {}, open=False)
    assert data(host.snapshot())["aboutOpen"] is False

    host.tap("SetAbout", {"open": False})
    assert data(host.snapshot())["aboutOpen"] is False


def test_creating_a_note_pushes_its_editor(app: ModuleType) -> None:
    """Python owns the back stack; the host is told the route only to keep it."""
    host = Host(app, follow_navigation=False)
    host.tap("NewNote")
    snapshot = host.snapshot()

    assert host.titles[0] == ""
    assert stack(snapshot) == ["NotesRoute", "EditorRoute"]
    assert data(snapshot)["noteId"] == 3
    assert host.ran == [("haptic", {}), ("navigate", {"route": editor(3)})]

    # The host's echo of the route on top changes nothing, and replays nothing.
    host.follow(editor(3))
    assert stack(host.snapshot()) == ["NotesRoute", "EditorRoute"]
    assert host.ran == []


def test_a_route_this_app_does_not_know_leaves_the_screen_where_it_was(
    app: ModuleType,
) -> None:
    host = Host(app)
    host.follow("somewhere/unknown")
    assert stack(host.snapshot()) == ["NotesRoute"]


def test_opening_and_leaving_a_note_round_trips(app: ModuleType) -> None:
    host = Host(app)
    host.tap("OpenNote", {"note_id": 1})
    assert stack(host.snapshot()) == ["NotesRoute", "EditorRoute"]

    host.tap("LeaveEditor")
    assert stack(host.snapshot()) == ["NotesRoute"]
    assert host.titles == ["Try it", "Welcome"]


def test_system_back_leaves_the_editor_and_closes_the_app_from_the_list(
    app: ModuleType,
) -> None:
    host = Host(app)
    host.tap("OpenNote", {"note_id": 1})
    host.lifecycle("onBackRequested")
    assert stack(host.snapshot()) == ["NotesRoute"]

    host.lifecycle("onBackRequested")
    assert effects(host.snapshot()) == [("finish", {})]


def test_the_list_keeps_its_state_while_a_note_is_open(app: ModuleType) -> None:
    """The list's view model lives under the editor rather than being rebuilt.

    Its filter is still set when the user comes back, and it followed the
    repository meanwhile, so the edit made on the editor is on the list.
    """
    host = Host(app)
    host.tap("SetPreviews", value=False)
    host.tap("NewNote")
    host.tap("SetTitle", value="Half-typed")

    host.tap("LeaveEditor")
    assert data(host.snapshot())["previews"] is False
    assert "Half-typed" in texts(host)


def test_a_deep_link_to_a_deleted_note_says_so_and_goes_back(
    app: ModuleType,
) -> None:
    host = Host(app, route=editor(99), repo=a_store([(7, "Only")]))
    assert stack(host.snapshot()) == ["NotesRoute", "EditorRoute"]
    assert "This note no longer exists." in texts(host)

    host.tap("LeaveEditor")
    assert "Only" in texts(host)


def test_the_host_route_opens_above_the_saved_stack(app: ModuleType) -> None:
    saved = _saved(("NotesRoute", {"previews": False}))
    snapshot = Host(app, route=editor(1), restore=saved).snapshot()
    assert stack(snapshot) == ["NotesRoute", "EditorRoute"]
    assert snapshot["metadata"]["data"]["stack"][0]["state"]["previews"] is False


def test_typing_updates_the_note_being_edited(app: ModuleType) -> None:
    host = Host(app)
    host.tap("NewNote")
    host.tap("SetTitle", value="Groceries")
    host.tap("SetBody", value="Milk\nBread")
    assert host.titles[0] == "Groceries"
    assert held_of(host, 3).body == "Milk\nBread"

    # The list describes its own size, from a rule in the domain.
    host.tap("LeaveEditor")
    assert "3 notes" in texts(host)


def test_the_editor_bar_is_an_icon_button_beside_a_rule(app: ModuleType) -> None:
    """The way back is a glyph, and the rule is a component, not a box."""
    host = Host(app)
    host.tap("OpenNote", {"note_id": 2})
    snapshot = host.snapshot()
    assert len(nodes(snapshot, "IconButton")) == 1
    assert [
        (icon["contentDescription"], icon["imageVector"]["name"])
        for icon in nodes(snapshot, "Icon")
    ] == [("Back to notes", "AutoMirrored.Filled.ArrowBack")]
    assert [rule.get("color") for rule in nodes(snapshot, "VerticalDivider")] == [None]


def test_each_row_deletes_only_its_own_note(app: ModuleType) -> None:
    host = Host(app)
    host.tap("DeleteNote", {"note_id": 1})
    assert host.titles == ["Try it"]
    # The deletion is on screen in the same snapshot.
    assert "Welcome" not in texts(host)


def test_deleting_the_open_note_returns_to_the_list(app: ModuleType) -> None:
    host = Host(app)
    host.tap("OpenNote", {"note_id": 2})
    host.tap("RemoveNote")
    assert stack(host.snapshot()) == ["NotesRoute"]
    assert host.titles == ["Welcome"]
    assert "Try it" not in texts(host)


def test_a_cleared_title_is_stored_empty_and_reads_as_a_note(app: ModuleType) -> None:
    host = Host(app)
    host.tap("OpenNote", {"note_id": 1})
    host.tap("SetTitle", value="")
    # Stored as the user left it; the placeholder belongs to the view, not the data.
    assert held_of(host, 1).title == ""
    assert "Untitled" in texts(host)


def test_an_empty_body_previews_itself_clearly(app: ModuleType) -> None:
    host = Host(app)
    host.tap("OpenNote", {"note_id": 1})
    host.tap("SetBody", value="   ")
    host.tap("LeaveEditor")
    assert "No additional text" in texts(host)


def test_half_typed_text_survives_process_death(app: ModuleType) -> None:
    """Death costs the saved stack, and the repository keeps the work.

    Those are two different rescues and the test needs both: the stack is what
    the host hands back, and storage is what outlives the process on its own.
    """
    disk = a_store()
    first = Host(app, repo=disk)
    first.tap("NewNote")
    first.tap("SetTitle", value="Half-typed")
    first.tap("SetBody", value="interrupted mid-sentence")
    published = first.snapshot()["metadata"]["data"]

    # A brand new process, same storage, and the bytes the host kept.
    second = Host(app, repo=disk, route=editor(3), restore=json.dumps(published))
    snapshot = second.snapshot()
    assert stack(snapshot) == ["NotesRoute", "EditorRoute"]
    assert second.titles[0] == "Half-typed"
    assert "Half-typed" in [props["value"] for props in nodes(snapshot, "TextField")]

    # And the restored editor is still editable, not merely readable.
    second.tap("SetBody", value="still here")
    assert held_of(second, 3).body == "still here"


@pytest.mark.parametrize(
    "restore",
    [
        "",
        "not json",
        "[]",
        '"a string"',
        '{"stack": 7}',
        '{"stack": [{"route": {"fields": {}, "route": "nowhere"}, "state": {}}]}',
        '{"route": "notes", "surprise": 1}',
    ],
)
def test_a_save_that_cannot_be_understood_still_starts_the_app(
    app: ModuleType, restore: str
) -> None:
    host = Host(app, restore=restore)
    assert stack(host.snapshot()) == ["NotesRoute"]
    assert host.titles == ["Try it", "Welcome"]
    assert host.error == ""


def test_a_save_with_one_bad_field_is_refused_whole_rather_than_half_applied(
    app: ModuleType,
) -> None:
    """The declared state makes partial recovery impossible, and that is the point.

    The codec either accepts the save exactly as written or refuses it, so a
    restore never produces a state the user never had.
    """
    saved = _saved(("NotesRoute", {"previews": "not a boolean"}))
    host = Host(app, restore=saved)
    assert data(host.snapshot())["previews"] is True
    assert titles_of(host) == ["Try it", "Welcome"]
