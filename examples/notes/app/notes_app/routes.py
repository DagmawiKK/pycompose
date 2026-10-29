"""Where the app can go: the list, and one note's editor."""

from __future__ import annotations

from pycompose.app import Route


class NotesRoute(Route):
    """The list of every note."""


class EditorRoute(Route):
    """One note's editor.

    Attributes:
        note_id: The note being edited.
    """

    note_id: int
