"""The app's domain: what a note is, and what you can do with notes.

Re-exported so callers reach for ``domain.Notes`` rather than the module path,
and so the layer has one obvious front door.
"""

from __future__ import annotations

from notes_app.domain.models import Note, NotesRepo
from notes_app.domain.usecases import Notes, count_line, newest_first

__all__ = [
    "Note",
    "Notes",
    "NotesRepo",
    "count_line",
    "newest_first",
]
