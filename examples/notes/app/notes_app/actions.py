"""The transitions a user can trigger.

Each handler is session-native: its first parameter is ``session``, the shell
itself rather than the whole snapshot, and returning that shell — or
``respond(shell, *effects)`` — is the whole of the transition. The version
counter, the rebuilt screen and the shell encoding are the framework's work.

Navigation is *requested* rather than performed — an action returns a
``navigate`` effect and the host echoes the destination back as
``on_route_changed`` — which keeps the boundary one-directional and means Python
never learns what a route means on the device.

Each handler is a plain function: its parameters after ``session`` are the
fields a control binds or an event supplies, and its keyword-only parameters
are what the container provides. Every row binds its note's id with
``with_args``, so one handler serves every row.
"""

from __future__ import annotations

from notes_app.domain import Notes
from notes_app.state import (
    LIST_ROUTE,
    Session,
    detail_route,
    editing_note,
    note_in,
    showing_list,
)
from pycompose import Registry
from pycompose.core.effect import Effect
from pycompose.state import ShellResponse, respond

actions = Registry()


@actions
def new_note(
    session: Session,
    *,
    notes: Notes,
) -> Session | ShellResponse:
    """Create a note and ask the host to open it.

    Args:
        session: The session shell before the tap.
        notes: What the app can do with notes.

    Returns:
        The unchanged shell, carrying a navigate effect for the new note.
    """
    note_id = notes.create()
    return respond(
        session,
        Effect("haptic"),
        Effect("navigate", {"route": detail_route(note_id)}),
    )


@actions
def open_note(
    session: Session,
    note_id: int,
    *,
    notes: Notes,
) -> Session | ShellResponse:
    """Open one note's editor.

    Args:
        session: The session shell before the tap.
        note_id: The note bound by the row that was tapped.
        notes: What the app can do with notes.

    Returns:
        The unchanged shell when the note is gone, else a navigate effect for
        that note. The route itself is not moved here: the host echoes it back
        as on_route_changed, so there is exactly one source of truth for what
        is showing.
    """
    if notes.get(note_id) is None:
        # The row names a note that no longer exists. Staying put beats
        # navigating to a destination the view-model would bounce back from.
        return session
    return respond(session, Effect("navigate", {"route": detail_route(note_id)}))


@actions
def on_route_changed(session: Session, route: str) -> Session:
    """Render the screen the host asked for.

    The host owns the route string and hands it back as an ordinary inbound
    action, so navigation no longer rebuilds this session — which is what lets a
    view-model outlive a screen change.

    Args:
        session: The session shell before the route change.
        route: The destination the host is now showing.

    Returns:
        The shell for that route, or the unchanged one when it is not a
        destination this app knows.
    """
    if route != LIST_ROUTE and note_in(route) is None:
        # An unknown route is not a screen. Staying put beats rendering nothing.
        return session
    return session.evolve(route=route)


@actions
def set_title(
    session: Session,
    note_id: int,
    value: str,
    *,
    notes: Notes,
) -> Session:
    """Record the title field's current text.

    Args:
        session: The session shell before the keystroke.
        note_id: The note bound by the field.
        value: The field's text, supplied by the event.
        notes: What the app can do with notes.

    Returns:
        The unchanged shell; the note itself was retitled in the repository.
    """
    if not _is_editing(session, note_id, notes):
        return session
    notes.rename(note_id, value)
    return session


@actions
def set_title_caret(session: Session, value: int) -> Session:
    """Record where the caret sits in the title.

    The field is controlled, so this is not a nicety: without a caret the
    snapshot would send, the next keystroke would reset where the user left it.

    Args:
        session: The session shell before the caret moved.
        value: Where the caret sits, supplied by the event.

    Returns:
        The shell with the caret where it was left.
    """
    return session.evolve(title_caret=int(value))


@actions
def set_body_caret(session: Session, value: int) -> Session:
    """Record where the caret sits in the body.

    Args:
        session: The session shell before the caret moved.
        value: Where the caret sits, supplied by the event.

    Returns:
        The shell with the caret where it was left.
    """
    return session.evolve(body_caret=int(value))


@actions
def set_body(
    session: Session,
    note_id: int,
    value: str,
    *,
    notes: Notes,
) -> Session:
    """Record the body field's current text.

    Args:
        session: The session shell before the keystroke.
        note_id: The note bound by the field.
        value: The field's text, supplied by the event.
        notes: What the app can do with notes.

    Returns:
        The unchanged shell; the note's text was replaced in the repository.
    """
    if not _is_editing(session, note_id, notes):
        return session
    notes.retext(note_id, value)
    return session


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
def delete_note(
    session: Session,
    note_id: int,
    *,
    notes: Notes,
) -> Session | ShellResponse:
    """Delete one note and return to the list.

    Args:
        session: The session shell before the tap.
        note_id: The note bound by the control that was tapped.
        notes: What the app can do with notes.

    Returns:
        The unchanged shell when the note is already gone, else a request to
        return to the list.
    """
    if notes.get(note_id) is None:
        return session
    notes.delete(note_id)
    return respond(
        session,
        Effect("haptic"),
        Effect("navigate", {"route": LIST_ROUTE}),
    )


@actions
def go_back(session: Session) -> Session | ShellResponse:
    """Return to the list from the editor.

    Args:
        session: The session shell before the tap.

    Returns:
        The unchanged shell, carrying a navigate effect for the list.
    """
    return respond(session, Effect("navigate", {"route": LIST_ROUTE}))


@actions
def set_about(session: Session, open: bool) -> Session:
    """Show or hide the about sheet.

    The sheet's own ``onOpenChange`` reports what it settled on through this
    same transition, so one handler serves the button that opens it, the button
    that closes it, and the swipe or scrim tap that dismisses it: the app always
    assigns the value it was handed rather than toggling what it believed.

    Args:
        session: The session shell before the change.
        open: The visibility the control or the sheet stated.

    Returns:
        The shell with the sheet's visibility assigned.
    """
    return session.evolve(about_open=open)


@actions
def set_previews(session: Session, value: bool) -> Session:
    """Show or hide the line of body text under each row's title.

    The switch reports the state it settled on, so the handler assigns what it
    was handed rather than toggling what it believed.

    Args:
        session: The session shell before the flip.
        value: The value the switch is now showing.

    Returns:
        The shell showing or hiding every row's preview.
    """
    return session.evolve(previews=value)


@actions
def set_listing(session: Session, value: str) -> Session:
    """Show every note, or only the ones carrying text.

    Each bar item bakes the filter it stands for into its own binding, so the
    tap carries no data and the host never chooses one for the user. A listing
    can outlive the set of filters it was written against: the screen shows the
    whole list for a value it does not know rather than an empty screen.

    Args:
        session: The session shell before the tap.
        value: The filter baked into the item that was tapped.

    Returns:
        The shell listing under that filter.
    """
    return session.evolve(listing=value)


@actions
def on_back_requested(
    session: Session,
    *,
    notes: Notes,
) -> Session | ShellResponse:
    """Handle the system back gesture the way a NavController would.

    Args:
        session: The session shell before the gesture.
        notes: What the app can do with notes.

    Returns:
        The unchanged shell, asking the host to close the app when there is
        nowhere left to go back to, and to return to the list otherwise.
    """
    if showing_list(session, notes.list()):
        return respond(session, Effect("finish"))
    return respond(session, Effect("navigate", {"route": LIST_ROUTE}))


@actions
def on_config_changed(session: Session, dark_mode: bool) -> Session:
    """Repaint when the device's appearance changes.

    The host reports orientation, locale and density too; this app reads only
    the one fact its palette depends on.

    Args:
        session: The session shell before the configuration changed.
        dark_mode: Whether the device is in dark mode.

    Returns:
        The shell in the palette matching the new appearance.
    """
    return session.evolve(dark=dark_mode)
