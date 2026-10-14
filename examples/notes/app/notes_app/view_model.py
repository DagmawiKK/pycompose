"""The view-model: declared state becomes one immutable snapshot.

The app's state is in two parts, and keeping them apart is the point:

* the **session shell** — route and appearance. Small, and the only part the host
  must be able to restore after process death.
* the **notes partition** — the feature's own data, attached only while a screen
  actually shows notes.

That split is what stops a keystroke in one screen from re-encoding everything
the other fourteen features are holding.

The only decision made here is which screen belongs on screen. A detail route
naming a note that no longer exists falls back to the list, which is what a real
``NavController`` does when its destination has been popped out from under it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from notes_app.handlers import Handlers
from notes_app.state import (
    LIST_ROUTE,
    Note,
    NotesState,
    Session,
    note_in,
    seeded,
    seeded_session,
)
from notes_app.views import editor_screen, list_screen
from pycompose.core.effect import Effect
from pycompose.errors import StateError
from pycompose.state import AppState, State
from pycompose.utils.json_canonical import thaw_json

NOTES = "notes"


def snapshot(
    session: Session,
    notes: NotesState,
    version: int,
    handlers: Handlers,
    effects: tuple[Effect, ...] = (),
) -> State:
    """Return the snapshot one screen of this state produces.

    Args:
        session: The session shell.
        notes: The notes partition.
        version: Monotonic snapshot counter, advanced once per change.
        handlers: Action references the screen binds to.
        effects: One-shot host requests to run once with this snapshot.

    Returns:
        A State carrying the screen, the shell and the notes partition.
    """
    editing = editing_note(session, notes)
    root = (
        list_screen(id="screen", state=notes, session=session, handlers=handlers)
        if editing is None
        else editor_screen(
            id="screen", note=editing, session=session, handlers=handlers
        )
    )
    return State(
        root=root, version=version, app=session, slices={NOTES: notes}, effects=effects
    )


def editing_note(session: Session, notes: NotesState) -> Note | None:
    """Return the note the current route is editing.

    Args:
        session: The session shell, which owns the route.
        notes: The notes partition.

    Returns:
        The note, or None when the list belongs on screen.
    """
    note_id = note_in(session.route)
    return notes.find(note_id) if note_id is not None else None


def showing_list(session: Session, notes: NotesState) -> bool:
    """Return whether the list is what belongs on screen.

    Args:
        session: The session shell, which owns the route.
        notes: The notes partition.

    Returns:
        True for the list route and for a detail route with no live note.
    """
    return editing_note(session, notes) is None


def of(state: State) -> tuple[Session, NotesState]:
    """Return the app state a snapshot was built from.

    Args:
        state: The snapshot a transition starts from.

    Returns:
        The session shell and the notes partition.
    """
    return decode(state.data)


def decode(published: object) -> tuple[Session, NotesState]:
    """Return the app state a published payload describes.

    The shell and a feature partition share one payload, so each decodes only
    the keys it owns.

    "No save at all" and "a save holding no notes" are different states and are
    treated differently: the first seeds the app, the second is what a user who
    deleted everything meant. A save that cannot be understood falls back rather
    than raising, because this runs during boot and a corrupt save must not stop
    the app starting.

    Args:
        published: The decoded payload, or None when there is no save.

    Returns:
        The session shell and the notes partition.
    """
    if published is None:
        return seeded_session(), seeded()
    try:
        data = _as_object(published)
        return (
            Session.codec.decode(_mine(Session, data)),
            NotesState.codec.decode(_mine(NotesState, data)),
        )
    except StateError:
        return seeded_session(), seeded()


def _as_object(published: object) -> dict[str, Any]:
    """Return published data as a plain mapping.

    Args:
        published: The published payload.

    Returns:
        Its top-level keys.

    Raises:
        StateError: If the payload is not an object at all.
    """
    thawed = thaw_json(published)
    if not isinstance(thawed, Mapping):
        raise StateError("app state must be an object")
    return dict(thawed)


def _mine(part: type[AppState], published: Mapping[str, Any]) -> dict[str, Any]:
    """Return the top-level keys one part of the app owns.

    ``published`` is a plain mapping, whatever it was read from: JSON parsed
    from the host's bytes, or taken off a snapshot where the canonical freeze had
    already replaced it. Normalising once means an app never sees its state
    vanish between a boot and a keystroke.

    Args:
        part: The declared state asking for its own keys.
        published: The published payload, or anything unusable.

    Returns:
        The subset this part decodes from.
    """
    keys = set(part.codec.encode(part()))
    return {key: value for key, value in published.items() if key in keys}


__all__ = [
    "LIST_ROUTE",
    "NOTES",
    "NotesState",
    "Session",
    "decode",
    "editing_note",
    "of",
    "showing_list",
    "snapshot",
]
