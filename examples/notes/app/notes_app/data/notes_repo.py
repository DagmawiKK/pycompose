"""The data layer: how notes are actually kept.

The domain says what it needs from storage. This is where that is answered — on
disk, as JSON, through the library's ``Document``. Swapping it for something
else means writing one class with three methods; nothing above this line changes.
"""

from __future__ import annotations

from pathlib import Path

from notes_app.domain.models import Note
from pycompose.repository import Document

SEQUENCE = "notes.seq"


def _sequence_for(path: Path) -> Path:
    """Return the file remembering the largest identity ever issued.

    Args:
        path: Where the notes themselves are kept.

    Returns:
        The path of the counter that sits beside them.
    """
    return path.with_name(SEQUENCE)


class FileNotesRepo:
    """Notes kept as a JSON document in the app's own storage.

    A counter sits beside the document recording the largest identity ever
    issued. Recomputing it from what is held would let a deleted identity be
    handed out again, and a control still bound to it would then edit whatever
    replaced the note.
    """

    def __init__(self, document: Document[Note] | None = None) -> None:
        """Open the store.

        Args:
            document: The document to use, or None for the default.
        """
        self._document = (
            document if document is not None else Document("notes.json", Note)
        )
        self._sequence = _sequence_for(self._document.path)

    @property
    def path(self) -> Path:
        """Return where the notes are kept.

        Returns:
            The file path.
        """
        return self._document.path

    def highest_id(self) -> int:
        """Return the largest identity ever issued, including deleted ones.

        Returns:
            The remembered mark, or the largest held when nothing was recorded.
        """
        try:
            recorded = int(self._sequence.read_text(encoding="utf-8").strip())
        except (FileNotFoundError, ValueError):
            recorded = 0
        return max(recorded, self._largest_held())

    def load(self) -> list[Note]:
        """Return every note held.

        Returns:
            The stored notes.
        """
        return self._document.load()

    def store(self, notes: list[Note]) -> None:
        """Replace everything held, and remember the high-water mark.

        Args:
            notes: The notes to keep.
        """
        # Read the mark before the write: afterwards the highest held would
        # already equal the incoming one, and deleting the last note would walk
        # the counter backwards.
        mark = max(self.highest_id(), max((note.id for note in notes), default=0))
        self._document.save(notes)
        try:
            self._sequence.parent.mkdir(parents=True, exist_ok=True)
            self._sequence.write_text(str(mark), encoding="utf-8")
        except OSError:  # a lost counter is recoverable; the notes are not
            pass

    def _largest_held(self) -> int:
        """Return the largest identity currently stored.

        Returns:
            The largest held id, or zero when nothing is held.
        """
        return max((note.id for note in self._document.load()), default=0)


class MemoryNotesRepo:
    """Notes kept for the life of the session.

    The point of the ``Protocol`` is that this is a complete substitute for the
    file-backed one: a test can exercise every use case without touching disk.
    """

    def __init__(self, notes: list[Note] | None = None) -> None:
        """Open the store.

        Args:
            notes: What to start with, or None for empty.
        """
        self._notes = list(notes or [])
        self._mark = max((note.id for note in self._notes), default=0)

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
        return list(self._notes)

    def store(self, notes: list[Note]) -> None:
        """Replace everything held, remembering the mark it leaves behind.

        Args:
            notes: The notes to keep.
        """
        self._notes = list(notes)
        self._mark = max(self._mark, max((note.id for note in notes), default=0))
