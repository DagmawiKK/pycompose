"""The transitions a user can trigger.

Each handler is pure: it reads the snapshot, returns a new one, touches nothing
else. Navigation is *requested* rather than performed — an action returns a
``navigate`` effect and the host echoes the destination back as
``on_route_changed`` — which keeps the boundary one-directional and means Python
never learns what a route means on the device.

Every control binds its note's id, so one handler serves every row.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from notes_app.domain import Notes
from notes_app.state import LIST_ROUTE, Session, detail_route, note_in
from notes_app.view_model import editing_note, of, showing_list, snapshot
from pycompose import Registry, context
from pycompose.core.effect import Effect
from pycompose.state import State


class NoteId(TypedDict):
    note_id: int


class Edit(TypedDict):
    note_id: int
    value: str


class Caret(TypedDict):
    note_id: int
    value: int


class Route(TypedDict):
    route: str


class Nothing(TypedDict):
    pass


class Config(TypedDict):
    orientation: Literal["portrait", "landscape"]
    dark_mode: bool
    locale: str
    density: float


def _next(
    state: State,
    session: Session,
    *,
    effects: tuple[Effect, ...] = (),
) -> State:
    """Return the next snapshot after a change.

    The notes are read back from the repository rather than threaded through,
    because they are not part of the snapshot at all -- only the shell crosses
    the boundary. The route is deliberately untouched: a handler that wants a
    different screen asks the host for one, and the host echoes it back as
    ``on_route_changed``.

    Args:
        state: Snapshot before the transition.
        session: The session shell after the transition.
        effects: One-shot host requests to run once with this snapshot.

    Returns:
        The next snapshot, one version on.
    """
    notes = context().notes.list()
    return snapshot(session, notes, state.version + 1, effects=effects)


actions = Registry()


@actions
def new_note(
    state: State,
    payload: Nothing,
    *,
    notes: Notes,
) -> State:
    """Create a note and ask the host to open it.

    Args:
        state: Snapshot before the tap.
        payload: Empty; this command takes no event fields.
        notes: What the app can do with notes.

    Returns:
        The next snapshot, carrying a navigate effect for the new note.
    """
    note_id = notes.create()
    return _next(
        state,
        of(state),
        effects=(
            Effect("haptic"),
            Effect("navigate", {"route": detail_route(note_id)}),
        ),
    )


@actions
def open_note(state: State, payload: NoteId, *, notes: Notes) -> State:
    """Open one note's editor.

    Args:
        state: Snapshot before the tap.
        payload: Note id bound by the row that was tapped.
        notes: What the app can do with notes.

    Returns:
        The next snapshot, carrying a navigate effect for that note.
    """
    session = of(state)
    note_id = payload["note_id"]
    if notes.get(note_id) is None:
        # The row names a note that no longer exists. Staying put beats navigating
        # to a destination the view-model would immediately bounce back from.
        return _next(state, session)
    # The route is not moved here. The host echoes it back as on_route_changed,
    # so there is exactly one source of truth for what is showing and this
    # session is never rebuilt.
    return _next(
        state,
        session,
        effects=(Effect("navigate", {"route": detail_route(note_id)}),),
    )


@actions
def on_route_changed(state: State, payload: Route) -> State:
    """Render the screen the host asked for.

    The host owns the route string and hands it back as an ordinary inbound
    action, so navigation no longer rebuilds this session — which is what lets a
    view-model outlive a screen change.

    Args:
        state: Snapshot before the route change.
        payload: The destination the host is now showing.

    Returns:
        The next snapshot for that route, or an unchanged one when it is not a
        destination this app knows.
    """
    session = of(state)
    route = payload["route"]
    if route != LIST_ROUTE and note_in(route) is None:
        # An unknown route is not a screen. Staying put beats rendering nothing.
        return _next(state, session)
    return _next(state, session.evolve(route=route))


@actions
def set_title(state: State, payload: Edit, *, notes: Notes) -> State:
    """Record the title field's current text.

    Args:
        state: Snapshot before the keystroke.
        payload: Bound note id, plus event-supplied field text.
        notes: What the app can do with notes.

    Returns:
        The next snapshot with the note retitled.
    """
    session = of(state)
    if not _is_editing(session, payload["note_id"], notes):
        return _next(state, session)
    notes.rename(payload["note_id"], payload["value"])
    return _next(state, session)


@actions
def set_title_caret(state: State, payload: Caret, *, notes: Notes) -> State:
    """Record where the caret sits in the title.

    The field is controlled, so this is not a nicety: without a caret the
    snapshot would send, the next keystroke would reset where the user left it.

    Args:
        state: Snapshot before the caret moved.
        payload: Note id bound by the field that owns the caret.
        notes: What the app can do with notes.

    Returns:
        The next snapshot with the caret where it was left.
    """
    session = of(state)
    return _next(state, session.evolve(title_caret=int(payload["value"])))


@actions
def set_body_caret(state: State, payload: Caret, *, notes: Notes) -> State:
    """Record where the caret sits in the body.

    Args:
        state: Snapshot before the caret moved.
        payload: Note id bound by the field that owns the caret.
        notes: What the app can do with notes.

    Returns:
        The next snapshot with the caret where it was left.
    """
    session = of(state)
    return _next(state, session.evolve(body_caret=int(payload["value"])))


@actions
def set_body(state: State, payload: Edit, *, notes: Notes) -> State:
    """Record the body field's current text.

    Args:
        state: Snapshot before the keystroke.
        payload: Bound note id, plus event-supplied field text.
        notes: What the app can do with notes.

    Returns:
        The next snapshot with the note's text replaced.
    """
    session = of(state)
    if not _is_editing(session, payload["note_id"], notes):
        return _next(state, session)
    notes.retext(payload["note_id"], payload["value"])
    return _next(state, session)


def _is_editing(session: Session, note_id: int, notes: Notes) -> bool:
    """Return whether the current route is editing this note.

    A stale control must be harmless rather than destructive, so an edit for a
    note the user has already navigated away from is ignored.

    Args:
        session: The session shell.
        note_id: Note the control was bound to.
        notes: What the app can do with notes.

    Returns:
        True when that note is the one on screen.
    """
    editing = editing_note(session, notes.list())
    return editing is not None and editing.id == note_id


@actions
def delete_note(state: State, payload: NoteId, *, notes: Notes) -> State:
    """Delete one note and return to the list.

    Args:
        state: Snapshot before the tap.
        payload: Note id bound by the control that was tapped.
        notes: What the app can do with notes.

    Returns:
        The next snapshot without that note, and a request to return to the list.
    """
    session = of(state)
    if notes.get(payload["note_id"]) is None:
        return _next(state, session)
    notes.delete(payload["note_id"])
    return _next(
        state,
        session,
        effects=(Effect("haptic"), Effect("navigate", {"route": LIST_ROUTE})),
    )


@actions
def go_back(state: State, payload: Nothing) -> State:
    """Return to the list from the editor.

    Args:
        state: Snapshot before the tap.
        payload: Empty; this command takes no event fields.

    Returns:
        The next snapshot, carrying a navigate effect for the list.
    """
    return _next(
        state,
        of(state),
        effects=(Effect("navigate", {"route": LIST_ROUTE}),),
    )


@actions
def show_about(state: State, payload: Nothing) -> State:
    """Explain where the interface comes from.

    Args:
        state: Snapshot before the tap.
        payload: Empty; this command takes no event fields.

    Returns:
        The same screen plus a host toast.
    """
    return _next(
        state,
        of(state),
        effects=(
            Effect("toast", {"message": "Every control here is native Material 3."}),
        ),
    )


@actions
def on_back_requested(state: State, payload: Nothing, *, notes: Notes) -> State:
    """Handle the system back gesture the way a NavController would.

    Args:
        state: Snapshot before the gesture.
        payload: Empty; the host sends nothing extra.
        notes: What the app can do with notes.

    Returns:
        The list from anywhere but the list, or a snapshot asking the host to
        close the app when there is nowhere left to go back to.
    """
    session = of(state)
    if showing_list(session, notes.list()):
        return _next(state, session, effects=(Effect("finish"),))
    return _next(state, session, effects=(Effect("navigate", {"route": LIST_ROUTE}),))


@actions
def on_config_changed(state: State, payload: Config) -> State:
    """Repaint when the device's appearance changes.

    Args:
        state: Snapshot before the configuration changed.
        payload: Orientation, dark mode, locale and density, from the host.

    Returns:
        The next snapshot in the palette matching the new appearance.
    """
    return _next(state, of(state).evolve(dark=payload["dark_mode"]))
