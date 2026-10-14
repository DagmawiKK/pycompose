"""The view-model: the notes plus the shell become one snapshot.

The notes are read from storage when a screen needs them, rather than carried in
the snapshot. That is what Phase 3 bought: a screen rendering a thousand notes no
longer re-encodes them on every keystroke, and the host's ``Bundle`` never sees
them at all. Only the session shell crosses the boundary.
"""

from __future__ import annotations

from typing import cast

from notes_app.domain.models import Note, NotesRepo
from notes_app.domain.usecases import get_note, list_notes
from notes_app.state import LIST_ROUTE, Session, note_in, seeded_session
from notes_app.views import editor_screen, list_screen
from pycompose.core.effect import Effect
from pycompose.errors import StateError
from pycompose.state import State

NOTES = "notes"


def snapshot(
    session: Session,
    notes: list[Note],
    version: int,
    effects: tuple[Effect, ...] = (),
) -> State:
    """Return the snapshot one screen of this state produces.

    Args:
        session: The session shell.
        notes: The notes to render, newest first.
        version: Monotonic snapshot counter, advanced once per change.
        effects: One-shot host requests to run once with this snapshot.

    Returns:
        A State carrying the screen and the session shell.
    """
    editing = editing_note(session, notes)
    root = (
        list_screen(id="screen", notes=notes, session=session)
        if editing is None
        else editor_screen(id="screen", note=editing, session=session)
    )
    return State(root=root, version=version, app=session, effects=effects)


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


def held(repo: NotesRepo) -> list[Note]:
    """Return every note a repository holds, newest first.

    Args:
        repo: Where the notes are held.

    Returns:
        The stored notes.
    """
    return list_notes(repo)


def find(repo: object, note_id: int) -> Note | None:
    """Return one note from a repository, when it is still there.

    Args:
        repo: Anything satisfying the notes repository protocol.
        note_id: Identity to look for.

    Returns:
        The note, or None.
    """
    return get_note(repo, note_id)  # type: ignore[arg-type]


def of(state: State) -> Session:
    """Return the session shell a snapshot was built from.

    Args:
        state: The snapshot a transition starts from.

    Returns:
        The decoded shell, or a fresh one when the data is unusable. A corrupt
        shell must not stop the app starting.
    """
    try:
        return cast("Session", Session.codec.decode(state.data))
    except StateError:
        return seeded_session()


__all__ = [
    "LIST_ROUTE",
    "Note",
    "Session",
    "editing_note",
    "held",
    "of",
    "showing_list",
    "snapshot",
]
