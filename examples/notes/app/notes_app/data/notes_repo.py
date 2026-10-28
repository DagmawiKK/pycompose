"""The data layer: how notes are actually kept.

The domain says what it needs from storage. This is where that is answered: a
SQLite database in the app's own storage, one row per note. A change writes one
row, so typing into a note costs the same with ten notes as with ten thousand,
and a write is durable when it commits.

SQLite connections belong to the thread that opened them, so every statement
runs on the session's one storage thread, in the order it was asked for. The
loop never waits on the disk: a write is queued and the caller moves on.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from notes_app.domain.models import Note
from pycompose.app import to_thread
from pycompose.repository import root

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS notes ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, body TEXT NOT NULL)"
)


class SqliteNotesRepo:
    """Notes kept in SQLite in the app's storage.

    ``AUTOINCREMENT`` remembers the largest identity ever issued, deletions
    included, so an identity is never handed out twice.

    Args:
        path: The database file, or None for ``notes.db`` in the app's storage.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else root() / "notes.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection: sqlite3.Connection | None = None
        # Read once as the session starts, on whatever thread builds the
        # container; from here on only the storage thread touches the file.
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(SCHEMA)
            db.commit()
            self._notes = [
                Note(*row) for row in db.execute("SELECT id, title, body FROM notes")
            ]
            mark = db.execute(
                "SELECT seq FROM sqlite_sequence WHERE name = 'notes'"
            ).fetchone()
        self._mark: int = max(
            int(mark[0]) if mark else 0, *(n.id for n in self._notes), 0
        )

    def highest_id(self) -> int:
        """Return the largest identity ever issued, including deleted ones.

        Returns:
            The mark as the session started.
        """
        return self._mark

    def load(self) -> list[Note]:
        """Return every note as the session started.

        Returns:
            The stored notes.
        """
        return list(self._notes)

    def insert(self, note: Note) -> None:
        """Queue one new note's row.

        Args:
            note: The note, with the identity it took.
        """
        self._write(
            "INSERT INTO notes (id, title, body) VALUES (?, ?, ?)",
            (note.id, note.title, note.body),
        )

    def update(self, note: Note) -> None:
        """Queue one note's row being rewritten.

        Args:
            note: The note as it is now.
        """
        self._write(
            "UPDATE notes SET title = ?, body = ? WHERE id = ?",
            (note.title, note.body, note.id),
        )

    def delete(self, note_id: int) -> None:
        """Queue one note's row being removed.

        Args:
            note_id: The note to remove.
        """
        self._write("DELETE FROM notes WHERE id = ?", (note_id,))

    def close(self) -> None:
        """Close the connection once every queued write is done."""
        to_thread("storage", self._close)

    def _write(self, statement: str, parameters: tuple[object, ...]) -> None:
        to_thread("storage", self._execute, statement, parameters)

    def _execute(self, statement: str, parameters: tuple[object, ...]) -> None:
        if self._connection is None:
            self._connection = sqlite3.connect(self.path)
            # Durable at each commit without a sync per write: WAL's default.
            self._connection.execute("PRAGMA synchronous=NORMAL")
        with self._connection:
            self._connection.execute(statement, parameters)

    def _close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


class MemoryNotesRepo:
    """Notes kept for the life of the session.

    The point of the ``Protocol`` is that this is a complete substitute for the
    SQLite one: a test can exercise every use case without touching disk.

    Args:
        notes: What to start with, or None for empty.
    """

    def __init__(self, notes: list[Note] | None = None) -> None:
        self._notes = {note.id: note for note in notes or []}
        self._mark = max(self._notes, default=0)

    def highest_id(self) -> int:
        """Return the largest identity ever issued, including deleted ones.

        Returns:
            The remembered mark.
        """
        return self._mark

    def load(self) -> list[Note]:
        """Return every note held.

        Returns:
            A copy, so a caller cannot mutate the store by accident.
        """
        return list(self._notes.values())

    def insert(self, note: Note) -> None:
        """Keep one new note.

        Args:
            note: The note, with the identity it took.
        """
        self._notes[note.id] = note
        self._mark = max(self._mark, note.id)

    def update(self, note: Note) -> None:
        """Replace one note.

        Args:
            note: The note as it is now.
        """
        self._notes[note.id] = note

    def delete(self, note_id: int) -> None:
        """Drop one note.

        Args:
            note_id: The note to remove.
        """
        self._notes.pop(note_id, None)

    def close(self) -> None:
        """Nothing to release: the notes live only in memory."""
