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

from notes_app.handlers import Handlers
from notes_app.state import LIST_ROUTE, NotesState, Session, detail_route, note_in
from notes_app.view_model import editing_note, of, showing_list, snapshot
from pycompose import action
from pycompose.core.effect import Effect
from pycompose.state import Actions, State


class NoteId(TypedDict):
    note_id: int


class Edit(TypedDict):
    note_id: int
    value: str


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
    notes: NotesState,
    *,
    effects: tuple[Effect, ...] = (),
) -> State:
    """Return the next snapshot after a change to app state.

    Args:
        state: Snapshot before the transition.
        session: The session shell after the transition.
        notes: The notes partition after the transition.
        effects: One-shot host requests to run once with this snapshot.

    Returns:
        The next snapshot, one version on.
    """
    return snapshot(session, notes, state.version + 1, HANDLERS, effects)


@action
def new_note(state: State, payload: Nothing) -> State:  # noqa: ARG001
    """Create a note and ask the host to open it.

    Args:
        state: Snapshot before the tap.
        payload: Empty; this command takes no event fields.

    Returns:
        The next snapshot, carrying a navigate effect for the new note.
    """
    session, notes = of(state)
    created, note_id = notes.created()
    return _next(
        state,
        session,
        created,
        effects=(
            Effect("haptic"),
            Effect("navigate", {"route": detail_route(note_id)}),
        ),
    )


@action
def open_note(state: State, payload: NoteId) -> State:
    """Open one note's editor.

    Args:
        state: Snapshot before the tap.
        payload: Note id bound by the row that was tapped.

    Returns:
        The next snapshot, carrying a navigate effect for that note.
    """
    session, notes = of(state)
    note_id = payload["note_id"]
    if notes.find(note_id) is None:
        # The row names a note that no longer exists. Staying put beats navigating
        # to a destination the view-model would immediately bounce back from.
        return _next(state, session, notes)
    # The route is not moved here. The host echoes it back as on_route_changed,
    # so there is exactly one source of truth for what is showing and this
    # session is never rebuilt.
    return _next(
        state,
        session,
        notes,
        effects=(Effect("navigate", {"route": detail_route(note_id)}),),
    )


@action
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
    session, notes = of(state)
    route = payload["route"]
    if route != LIST_ROUTE and note_in(route) is None:
        # An unknown route is not a screen. Staying put beats rendering nothing.
        return _next(state, session, notes)
    return _next(state, session.evolve(route=route), notes)


@action
def set_title(state: State, payload: Edit) -> State:
    """Record the title field's current text.

    Args:
        state: Snapshot before the keystroke.
        payload: Bound note id, plus event-supplied field text.

    Returns:
        The next snapshot with the note retitled.
    """
    session, notes = of(state)
    if not _is_editing(session, notes, payload["note_id"]):
        return _next(state, session, notes)
    return _next(state, session, notes.retitled(payload["note_id"], payload["value"]))


@action
def set_body(state: State, payload: Edit) -> State:
    """Record the body field's current text.

    Args:
        state: Snapshot before the keystroke.
        payload: Bound note id, plus event-supplied field text.

    Returns:
        The next snapshot with the note's text replaced.
    """
    session, notes = of(state)
    if not _is_editing(session, notes, payload["note_id"]):
        return _next(state, session, notes)
    return _next(state, session, notes.retexted(payload["note_id"], payload["value"]))


def _is_editing(session: Session, notes: NotesState, note_id: int) -> bool:
    """Return whether the current route is editing this note.

    A stale control must be harmless rather than destructive, so an edit for a
    note the user has already navigated away from is ignored.

    Args:
        session: The session shell.
        notes: The notes partition.
        note_id: Note the control was bound to.

    Returns:
        True when that note is the one on screen.
    """
    editing = editing_note(session, notes)
    return editing is not None and editing.id == note_id


@action
def delete_note(state: State, payload: NoteId) -> State:
    """Delete one note and return to the list.

    Args:
        state: Snapshot before the tap.
        payload: Note id bound by the control that was tapped.

    Returns:
        The next snapshot without that note, and a request to return to the list.
    """
    session, notes = of(state)
    if notes.find(payload["note_id"]) is None:
        return _next(state, session, notes)
    return _next(
        state,
        session,
        notes.deleted(payload["note_id"]),
        effects=(Effect("haptic"), Effect("navigate", {"route": LIST_ROUTE})),
    )


@action
def go_back(state: State, payload: Nothing) -> State:  # noqa: ARG001
    """Return to the list from the editor.

    Args:
        state: Snapshot before the tap.
        payload: Empty; this command takes no event fields.

    Returns:
        The next snapshot, carrying a navigate effect for the list.
    """
    session, notes = of(state)
    return _next(
        state, session, notes, effects=(Effect("navigate", {"route": LIST_ROUTE}),)
    )


@action
def show_about(state: State, payload: Nothing) -> State:  # noqa: ARG001
    """Explain where the interface comes from.

    Args:
        state: Snapshot before the tap.
        payload: Empty; this command takes no event fields.

    Returns:
        The same screen plus a host toast.
    """
    session, notes = of(state)
    return _next(
        state,
        session,
        notes,
        effects=(
            Effect("toast", {"message": "Every control here is native Material 3."}),
        ),
    )


@action
def on_back_requested(state: State, payload: Nothing) -> State:  # noqa: ARG001
    """Handle the system back gesture the way a NavController would.

    Args:
        state: Snapshot before the gesture.
        payload: Empty; the host sends nothing extra.

    Returns:
        The list from anywhere but the list, or a snapshot asking the host to
        close the app when there is nowhere left to go back to.
    """
    session, notes = of(state)
    if showing_list(session, notes):
        return _next(state, session, notes, effects=(Effect("finish"),))
    return _next(
        state, session, notes, effects=(Effect("navigate", {"route": LIST_ROUTE}),)
    )


@action
def on_config_changed(state: State, payload: Config) -> State:
    """Repaint when the device's appearance changes.

    Args:
        state: Snapshot before the configuration changed.
        payload: Orientation, dark mode, locale and density, from the host.

    Returns:
        The next snapshot in the palette matching the new appearance.
    """
    session, notes = of(state)
    return _next(state, session.evolve(dark=payload["dark_mode"]), notes)


HANDLERS = Handlers(
    new_note=new_note,
    open_note=open_note,
    set_title=set_title,
    set_body=set_body,
    delete_note=delete_note,
    go_back=go_back,
    show_about=show_about,
)

# The runtime finds an app's registry by this exact module-level name.
actions = Actions(
    on_route_changed,
    new_note,
    open_note,
    set_title,
    set_body,
    delete_note,
    go_back,
    show_about,
    on_back_requested,
    on_config_changed,
)
