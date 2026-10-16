"""Use cases: what the app can do with notes.

Two shapes, because there are two kinds of rule here.

Functions for rules that depend on nothing but their arguments — counting,
ordering. They are ordinary module-level functions and stay that way; a class
around ``count_line`` would be ceremony Python does not need.

:class:`Notes` for rules that need storage. It holds the repository once and
hides it, so a caller never sees a ``NotesRepo`` and never assembles one. This
is the direction Clean Architecture insists on: the controller depends on the
use case, the use case depends on the repository interface, and nothing outside
this module knows the repository exists at all.
"""

from __future__ import annotations

from collections.abc import Callable

from notes_app.domain.models import Note, NotesRepo


def count_line(notes: list[Note]) -> str:
    """Return the summary the list shows under its title.

    How a collection describes its own size is a rule of the app, not a fact about
    storage, so it belongs here rather than on the state that happened to hold the
    notes last week.

    Args:
        notes: Every note held.

    Returns:
        A sentence describing how much is held.
    """
    total = len(notes)
    if total == 0:
        return "Nothing saved yet"
    noun = "note" if total == 1 else "notes"
    return f"{total} {noun}"


def newest_first(notes: list[Note]) -> list[Note]:
    """Return the notes in the order the list shows them.

    Args:
        notes: Every note held.

    Returns:
        The same notes, newest first.
    """
    return sorted(notes, key=lambda note: note.id, reverse=True)


def filled_share(notes: list[Note]) -> float:
    """Return the share of notes that carry a body.

    The about sheet's bar shows this fraction. It is a *provider* prop: the app
    states a number in the snapshot and the host hands Compose a lambda that
    reads it during composition, so the bar follows the notes with no Kotlin in
    the app at all.

    Args:
        notes: Every note held.

    Returns:
        Notes with a body over every note, or 0.0 when there are none.
    """
    if not notes:
        return 0.0
    return sum(1 for note in notes if note.body.strip()) / len(notes)


def carrying_text(notes: list[Note]) -> list[Note]:
    """Return the notes that carry a body, in the order they were given.

    "Carries text" is the same fact the about sheet's bar measures, so the
    filter and the bar can never disagree about what a filled note is.

    Args:
        notes: The notes to sift.

    Returns:
        Only the notes whose body has something in it.
    """
    return [note for note in notes if note.body.strip()]


class Notes:
    """Everything the app can do with notes, with the storage already bound.

    Callers hold one of these and never a repository. The storage
    backend is named in exactly one place in the app -- the wiring in
    ``container.py`` -- and a test swaps it by constructing this with
    something else.
    """

    def __init__(self, notes: NotesRepo) -> None:
        """Bind the use cases to a repository.

        Args:
            notes: Where the notes are kept.
        """
        self._notes = notes

    def list(self) -> list[Note]:
        """Return every note, newest first.

        Returns:
            The notes to render.
        """
        return newest_first(self._notes.load())

    def get(self, note_id: int) -> Note | None:
        """Return one note, when it is still there.

        Args:
            note_id: Identity to look for.

        Returns:
            The note, or None if it has been deleted.
        """
        return next((note for note in self._notes.load() if note.id == note_id), None)

    def create(self, title: str = "", body: str = "") -> int:
        """Create a note and return the id it took.

        Ids are the highest ever issued, never reused. Reusing one would let a
        stale control that still held the old id write into whatever replaced the
        note.

        Args:
            title: Headline for the new note.
            body: Text for the new note.

        Returns:
            The new note's id.
        """
        held = self._notes.load()
        next_id = self._notes.highest_id() + 1
        self._notes.store([Note(next_id, title, body), *held])
        return next_id

    def rename(self, note_id: int, title: str) -> None:
        """Change one note's title, if it still exists.

        Args:
            note_id: Identity to change.
            title: Its new headline.
        """
        self._rewrite(note_id, lambda note: note.retitled(title))

    def retext(self, note_id: int, body: str) -> None:
        """Change one note's text, if it still exists.

        Args:
            note_id: Identity to change.
            body: Its new text.
        """
        self._rewrite(note_id, lambda note: note.retexted(body))

    def delete(self, note_id: int) -> None:
        """Delete one note, if it still exists.

        Args:
            note_id: Identity to remove.
        """
        self._rewrite(note_id, lambda _note: None)

    def _rewrite(self, note_id: int, change: Callable[[Note], Note | None]) -> None:
        """Replace one note, or drop it, leaving the rest untouched.

        A note that is not there is not an error: a control can outlive the note
        it was bound to, and acting on a stale id must do nothing rather than
        damage whatever now holds that id.

        Args:
            note_id: Identity to change.
            change: Callable producing the note, or None to remove it.
        """
        held = self._notes.load()
        rewritten = []
        touched = False
        for note in held:
            if note.id != note_id:
                rewritten.append(note)
                continue
            touched = True
            replacement = change(note)
            if replacement is not None:
                rewritten.append(replacement)
        if touched:
            self._notes.store(rewritten)
