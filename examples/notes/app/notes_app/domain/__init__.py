"""The app's domain: what a note is, and what you can do with notes.

Re-exported so callers reach for ``domain.create_note`` rather than the module
path, and so the layer has one obvious front door.
"""

from __future__ import annotations

from notes_app.domain.models import Note, NotesRepo
from notes_app.domain.usecases import (
    count_line,
    create_note,
    delete_note,
    get_note,
    list_notes,
    newest_first,
    rename_note,
    retext_note,
)

__all__ = [
    "Note",
    "NotesRepo",
    "count_line",
    "create_note",
    "delete_note",
    "get_note",
    "list_notes",
    "newest_first",
    "rename_note",
    "retext_note",
]
