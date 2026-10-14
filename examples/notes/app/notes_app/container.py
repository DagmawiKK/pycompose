"""Where the app's long-lived objects live.

Google's manual dependency injection, in full: one container, built once, handed
to ``build`` by the session, and passed explicitly to anything that needs it.
There is no injection framework here and no framework is wanted -- a graph whose
wiring can only be discovered by running the app is harder to read than the code
it replaces.

This module is also the only place in the app that names a storage backend. Every
other module asks for ``Notes`` and gets it; swapping JSON for something else is
a change to the two lines below and nothing else.
"""

from __future__ import annotations

from notes_app.data.notes_repo import FileNotesRepo
from notes_app.domain.usecases import Notes


class AppContainer:
    """The app's graph. Every dependency the app has, in one place.

    Swap this for a test double and the whole app runs against it -- there is no
    other place a dependency could be hiding, which is the property the framework
    approaches buy and the reason this shape is worth the eight lines.
    """

    def __init__(self, notes: Notes) -> None:
        """Wire the app's dependencies.

        Args:
            notes: What the app can do with notes.
        """
        self.notes = notes


def build() -> AppContainer:
    """Return the container the session will retain for this process.

    Returns:
        A container backed by the app's own storage.
    """
    return AppContainer(Notes(FileNotesRepo()))
