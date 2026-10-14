"""Use cases: what the app can do to notes.

Plain functions. Kotlin needs a class per use case because of its injection
conventions; Python does not, and wrapping these would make the code longer
without making it clearer.

Each one takes a repository and returns the notes that should now be held. None
of them touches a screen, which is what makes them testable without one.
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


def list_notes(repo: NotesRepo) -> list[Note]:
    """Return every note, newest first.

    Args:
        repo: Where the notes are held.

    Returns:
        The notes to render.
    """
    return newest_first(repo.load())


def get_note(
    repo: NotesRepo,
    note_id: int,
) -> Note | None:
    """Return one note, when it is still there.

    Args:
        repo: Where the notes are held.
        note_id: Identity to look for.

    Returns:
        The note, or None if it has been deleted.
    """
    return next((note for note in repo.load() if note.id == note_id), None)


def create_note(repo: NotesRepo, title: str = "", body: str = "") -> int:
    """Create a note and return the id it took.

    Ids are the highest ever issued, never reused. Reusing one would let a stale
    control that still held the old id write into whatever replaced the note.

    Args:
        repo: Where the notes are held.
        title: Headline for the new note.
        body: Text for the new note.

    Returns:
        The new note's id.
    """
    held = repo.load()
    next_id = repo.highest_id() + 1
    repo.store([Note(next_id, title, body), *held])
    return next_id


def rename_note(
    repo: NotesRepo,
    note_id: int,
    title: str,
) -> None:
    """Change one note's title, if it still exists.

    Args:
        repo: Where the notes are held.
        note_id: Identity to change.
        title: Its new headline.
    """
    _rewrite(repo, note_id, lambda note: note.retitled(title))


def retext_note(
    repo: NotesRepo,
    note_id: int,
    body: str,
) -> None:
    """Change one note's text, if it still exists.

    Args:
        repo: Where the notes are held.
        note_id: Identity to change.
        body: Its new text.
    """
    _rewrite(repo, note_id, lambda note: note.retexted(body))


def delete_note(repo: NotesRepo, note_id: int) -> None:
    """Delete one note, if it still exists.

    Args:
        repo: Where the notes are held.
        note_id: Identity to remove.
    """
    _rewrite(repo, note_id, lambda _note: None)


def _rewrite(
    repo: NotesRepo,
    note_id: int,
    change: Callable[[Note], Note | None],
) -> None:
    """Replace one note, or drop it, leaving the rest untouched.

    A note that is not there is not an error: a control can outlive the note it
    was bound to, and acting on a stale id must do nothing rather than damage
    whatever now holds that id.

    Args:
        repo: Where the notes are held.
        note_id: Identity to change.
        change: Callable producing the note, or None to remove it.
    """
    held = repo.load()
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
        repo.store(rewritten)
