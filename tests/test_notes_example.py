"""The Notes example: model, view-model, navigation and rehydration.

Loaded from ``examples/notes`` by path, the way the on-device worker loads the
bundled demo. Nothing here is mocked below the bridge: these tests drive the real
emitter, the real validator and the real action registry, and they address every
control by the binding id the snapshot itself published.
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
    titles_of,
)


@pytest.fixture(scope="module")
def app() -> ModuleType:
    """Import the Notes app exactly as the Android worker does."""
    return load_notes_app()


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
    assert len(nodes(snapshot, "TextButton")) == 4


def test_the_scaffolds_slots_hold_the_bar_and_the_button(app: ModuleType) -> None:
    """The wire has one place for a child; the slot says where it composes.

    A Scaffold's floating button and bottom bar are the Scaffold's own content,
    not the body's, so they arrive marked with the slot the parent declared --
    and the rule under the header is a real divider, stated in dp.
    """
    snapshot = Host(app, follow_navigation=False).snapshot()
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

    The switch reports the value it settled on, and the handler assigns what it
    was handed rather than flipping what it believed -- which is what keeps a
    report from fighting the user. Stating the value is the whole interface.
    """
    host = Host(app, follow_navigation=False)
    assert data(host.snapshot())["previews"] is True
    assert [node["checked"] for node in nodes(host.snapshot(), "Switch")] == [True]

    host.tap("set_previews", value=False)
    snapshot = host.snapshot()
    assert data(snapshot)["previews"] is False
    assert [node["checked"] for node in nodes(snapshot, "Switch")] == [False]

    texts = [props["text"] for props in nodes(snapshot, "Text")]
    # The titles stay; the line of body under each one goes.
    assert "Try it" in texts
    assert "Welcome" in texts
    assert "Tap a note to edit it, or add one with the New button." not in texts
    assert "This app is written entirely in Python." not in texts


def test_the_filter_bar_narrows_the_list_without_leaving_it(app: ModuleType) -> None:
    """A navigation bar here is selection, not navigation: nothing moves.

    Each item bakes the filter it stands for into its own binding, so one
    handler serves both items and the tap carries no data; the one the session
    names is the selected one, and the rows and the count line follow the
    filter. A body of spaces carries no text, which is the same fact the about
    sheet's bar measures.
    """
    host = Host(
        app,
        follow_navigation=False,
        repo=a_store([(1, "Body", "words"), (2, "Blank", "   ")]),
    )
    assert [
        item["selected"] for item in nodes(host.snapshot(), "NavigationBarItem")
    ] == [True, False]

    host.tap("set_listing", {"value": "with_text"})
    snapshot = host.snapshot()
    assert data(snapshot)["listing"] == "with_text"
    assert data(snapshot)["route"] == "notes"
    assert [item["selected"] for item in nodes(snapshot, "NavigationBarItem")] == [
        False,
        True,
    ]
    texts = [props["text"] for props in nodes(snapshot, "Text")]
    assert "Body" in texts
    assert "Blank" not in texts
    assert "1 note" in texts


def test_a_filter_that_matches_nothing_names_the_filter(app: ModuleType) -> None:
    """An empty list is two different facts, and the screen says which one."""
    host = Host(app, follow_navigation=False, repo=a_store([(1, "Blank", "  ")]))
    assert "Blank" in [props["text"] for props in nodes(host.snapshot(), "Text")]

    host.tap("set_listing", {"value": "with_text"})
    texts = [props["text"] for props in nodes(host.snapshot(), "Text")]
    assert "No notes with text yet." in texts
    assert "No notes yet." not in texts


def test_a_listing_the_app_no_longer_knows_renders_the_whole_list(
    app: ModuleType,
) -> None:
    """A save can outlive the set of filters it was written against.

    The codec checks types, not domains, so a listing it does not recognise
    arrives here as an ordinary string; the screen shows every note rather than
    an empty screen nobody can explain.
    """
    saved = json.dumps({"route": "notes", "listing": "everything"})
    snapshot = Host(app, restore=saved).snapshot()
    assert data(snapshot)["listing"] == "everything"
    texts = [props["text"] for props in nodes(snapshot, "Text")]
    assert "Try it" in texts
    assert "Welcome" in texts


def test_the_about_bar_states_a_share_the_host_reads(app: ModuleType) -> None:
    """A provider prop: the app states a number, never a function.

    ``LinearProgressIndicator.progress`` is pinned as ``() -> Float``, which
    Python cannot hand over. The app's side of that parameter is an ordinary
    number in the snapshot, and the host reads it during composition -- so the
    bar follows the notes while the app writes no Kotlin and holds no callback.
    """
    host = Host(app, follow_navigation=False)
    seeded = nodes(host.snapshot(), "LinearProgressIndicator")
    assert [bar["progress"] for bar in seeded] == [1.0]

    # A note with no body yet: the share the app states follows the notes.
    host.tap("new_note")
    stated = nodes(host.snapshot(), "LinearProgressIndicator")[0]["progress"]
    assert stated == pytest.approx(2 / 3)


def test_every_icon_names_a_pinned_glyph_the_host_resolves(app: ModuleType) -> None:
    """An icon vocabulary prop: the app names a pinned icon, never a vector.

    ``Icon.imageVector`` is an ``ImageVector``, which exists only on the native
    side, so the snapshot carries the path under ``Icons`` and the host reads
    that property. Every glyph on the screen comes from that vocabulary, and the
    controls that are nothing but an icon say what they are in words.
    """
    host = Host(app, follow_navigation=False)
    icons = nodes(host.snapshot(), "Icon")
    assert [
        (icon["contentDescription"], icon["imageVector"]["name"]) for icon in icons
    ] == [
        ("About this app", "Filled.Info"),
        (None, "Filled.Home"),
        (None, "Filled.Edit"),
        ("New note", "Filled.Add"),
    ]


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
    host.tap("set_about", {"open": True})
    snapshot = host.snapshot()
    assert data(snapshot)["aboutOpen"] is True
    assert nodes(snapshot, "ModalBottomSheet")[0]["open"] is True

    # What the host sends once the sheet has settled: the user dismissed it.
    # This binding names no value, so the event is the one carrying it.
    host.tap("set_about", {}, open=False)
    assert data(host.snapshot())["aboutOpen"] is False

    host.tap("set_about", {"open": False})
    assert data(host.snapshot())["aboutOpen"] is False


def test_creating_a_note_requests_navigation_rather_than_moving_itself(
    app: ModuleType,
) -> None:
    """The app asks; the host decides. Nothing here relocates the screen alone."""
    host = Host(app, follow_navigation=False)
    host.tap("new_note")
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
    host.tap("new_note")
    host.follow("somewhere/unknown")
    assert data(host.snapshot())["route"] == "notes"


def test_opening_and_leaving_a_note_round_trips(app: ModuleType) -> None:
    host = Host(app)
    host.tap("open_note", {"note_id": 1})
    assert data(host.snapshot())["route"] == "note:1"

    host.tap("go_back")
    snapshot = host.snapshot()
    assert data(snapshot)["route"] == "notes"
    assert host.titles == ["Try it", "Welcome"]


def test_system_back_leaves_the_editor_and_closes_the_app_from_the_list(
    app: ModuleType,
) -> None:
    host = Host(app)
    host.tap("open_note", {"note_id": 1})
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
    host.tap("new_note")
    host.tap("set_title", value="Half-typed")
    assert host.titles[0] == "Half-typed"

    host.tap("go_back")
    host.tap("open_note", {"note_id": 3})
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
    saved = json.dumps({"route": "notes", "previews": False})
    assert (
        data(Host(app, route="note:1", restore=saved).snapshot())["route"] == "note:1"
    )


def test_typing_updates_the_note_being_edited(app: ModuleType) -> None:
    host = Host(app)
    host.tap("new_note")
    host.tap("set_title", value="Groceries")
    host.tap("set_body", value="Milk\nBread")
    assert host.titles[0] == "Groceries"
    assert held_of(host, 3).body == "Milk\nBread"

    # The list describes its own size, from a rule in the domain rather than
    # from whatever state happened to be carrying the notes.
    host.tap("go_back")
    assert "3 notes" in [props["text"] for props in nodes(host.snapshot(), "Text")]


def test_the_editor_bar_is_an_icon_button_beside_a_rule(app: ModuleType) -> None:
    """The way back is a glyph, and the rule is a component, not a box.

    An icon button has no text of its own, so its icon carries the label a
    screen reader reads; the divider is the host's to draw, in the theme's own
    colour.
    """
    host = Host(app)
    host.tap("open_note", {"note_id": 2})
    snapshot = host.snapshot()
    assert len(nodes(snapshot, "IconButton")) == 1
    assert [
        (icon["contentDescription"], icon["imageVector"]["name"])
        for icon in nodes(snapshot, "Icon")
    ] == [("Back to notes", "AutoMirrored.Filled.ArrowBack")]
    assert [rule.get("color") for rule in nodes(snapshot, "VerticalDivider")] == [None]


def test_each_row_deletes_only_its_own_note(app: ModuleType) -> None:
    host = Host(app)
    host.tap("delete_note", {"note_id": 1})
    assert host.titles == ["Try it"]


def test_deleting_the_open_note_returns_to_the_list(app: ModuleType) -> None:
    host = Host(app)
    host.tap("open_note", {"note_id": 2})
    host.tap("delete_note")
    snapshot = host.snapshot()
    assert data(snapshot)["route"] == "notes"
    assert host.titles == ["Welcome"]


def test_a_cleared_title_is_stored_empty_and_reads_as_a_note(app: ModuleType) -> None:
    host = Host(app)
    host.tap("open_note", {"note_id": 1})
    host.tap("set_title", value="")
    snapshot = host.snapshot()
    # Stored as the user left it; the placeholder belongs to the view, not the data.
    assert held_of(host, 1).title == ""
    assert "Untitled" in [props["text"] for props in nodes(snapshot, "Text")]


def test_an_empty_body_previews_itself_clearly(app: ModuleType) -> None:
    host = Host(app)
    host.tap("open_note", {"note_id": 1})
    host.tap("set_body", value="   ")
    host.tap("go_back")
    texts = [props["text"] for props in nodes(host.snapshot(), "Text")]
    assert "No additional text" in texts


def test_half_typed_text_survives_process_death(app: ModuleType) -> None:
    """Death costs the session shell and the repository keeps the work.

    Those are two different rescues and the test needs both: the shell is what
    the host hands back, and storage is what outlives the process on its own.
    """
    disk = a_store()
    first = Host(app, repo=disk)
    first.tap("new_note")
    first.tap("set_title", value="Half-typed")
    first.tap("set_body", value="interrupted mid-sentence")
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
    second.tap("set_body", value="still here")
    assert held_of(second, 3).body == "still here"


@pytest.mark.parametrize(
    "restore",
    [
        "",
        "not json",
        "[]",
        '"a string"',
        '{"route": 7}',
        '{"route": "notes", "previews": "maybe"}',
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
    saved = json.dumps({"route": "note:4", "previews": "not a boolean"})
    assert titles_of(Host(app, restore=saved)) == ["Try it", "Welcome"]
