"""Where the app's long-lived objects live.

Google's manual dependency injection, in full: one container, built once, handed
to ``build`` by the session, and passed explicitly to anything that needs it.
There is no injection framework here and no framework is wanted — a graph whose
wiring can only be discovered by running the app is harder to read than the code
it replaces, and the thing it buys is a handful of attributes.

The session finds the module-level ``container`` factory in ``main.py`` and calls
it exactly once, so the file handle inside is opened once per process rather
than once per keystroke.
"""

from __future__ import annotations

from notes_app.data.notes_repo import FileNotesRepo
from notes_app.domain.models import NotesRepo


class AppContainer:
    """The app's graph. Every dependency the app has, in one place.

    Swap this for a test double and the whole app runs against it -- there is no
    other place a dependency could be hiding, which is the property the framework
    approaches buy and the reason this shape is worth the eight lines.
    """

    def __init__(self, notes_repo: NotesRepo) -> None:
        """Wire the app's dependencies.

        Args:
            notes_repo: Where the notes are kept.
        """
        self.notes_repo = notes_repo


def build() -> AppContainer:
    """Return the container the session will retain for this process.

    Returns:
        A container backed by the app's own storage.
    """
    return AppContainer(FileNotesRepo())
