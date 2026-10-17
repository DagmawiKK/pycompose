"""The view-model: the notes plus the shell become one screen.

The notes are read from storage when a screen needs them, rather than carried in
the snapshot. That is what Phase 3 bought: a screen rendering a thousand notes no
longer re-encodes them on every keystroke, and the host's ``Bundle`` never sees
them at all. Only the session shell crosses the boundary. The version counter
and the effects are the framework's to carry, so a screen here is a pure
function of shell plus notes.
"""

from __future__ import annotations

from notes_app.domain.models import Note
from notes_app.state import Session, note_in
from notes_app.views import editor_screen, list_screen
from pycompose.core.node import Node

__all__ = ["editing_note", "screen", "showing_list"]


def screen(session: Session, notes: list[Note]) -> Node:
    """Return the screen one shell produces.

    Args:
        session: The session shell.
        notes: The notes to render, newest first.

    Returns:
        The root declaration for this shell.
    """
    editing = editing_note(session, notes)
    if editing is None:
        return list_screen(id="screen", notes=notes, session=session)
    return editor_screen(id="screen", note=editing, session=session)


def editing_note(session: Session, notes: list[Note]) -> Note | None:
    """Return the note the current route is editing.

    Args:
        session: The session shell, which owns the route.
        notes: Every note held.

    Returns:
        The note, or None when the list belongs on screen, or when the route
        names something that is no longer there.
    """
    note_id = note_in(session.route)
    if note_id is None:
        return None
    return next((note for note in notes if note.id == note_id), None)


def showing_list(session: Session, notes: list[Note]) -> bool:
    """Return whether the list is what belongs on screen.

    Args:
        session: The session shell, which owns the route.
        notes: Every note held.

    Returns:
        True for the list route and for a detail route with no live note.
    """
    return editing_note(session, notes) is None
