"""Where the app's long-lived objects live.

Google's manual dependency injection, in full: one container, built once, handed
to each destination's view model factory by the session, and passed explicitly
to anything that needs it. There is no injection framework here and no framework
is wanted -- a graph whose wiring can only be discovered by running the app is
harder to read than the code it replaces.

This module is also the only place in the app that names a storage backend. Every
other module asks for ``Notes`` and gets it; swapping JSON for something else is
a change to one line below and nothing else.
"""

from __future__ import annotations

from notes_app.data.notes_repo import FileNotesRepo
from notes_app.domain import Note, NotesRepo
from notes_app.domain.usecases import Notes
from pycompose.app import StateFlow


class AppContainer:
    """The app's graph. Every dependency the app has, in one place.

    Swap the repository for a test double and the whole app runs against it --
    there is no other place a dependency could be hiding.

    Args:
        repo: Where the notes are kept.
    """

    def __init__(self, repo: NotesRepo) -> None:
        self.notes = Notes(repo, changed=self._publish)
        self.listing: StateFlow[tuple[Note, ...]] = StateFlow(tuple(self.notes.list()))
        """Every note, newest first, for the screens that follow storage."""

    def _publish(self, notes: list[Note]) -> None:
        self.listing.value = tuple(notes)


def build() -> AppContainer:
    """Return the container the session will retain for this process.

    Returns:
        A container backed by the app's own storage.
    """
    return AppContainer(FileNotesRepo())
