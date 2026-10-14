"""The domain layer: what a note *is*, and what you can do with notes.

Nothing here imports a screen, a file, or the library. The rules an app follows
live in :mod:`notes_app.domain.usecases` and are written as plain functions,
because a class with an ``__call__`` is ceremony Python does not need.

The only outward edge is :class:`NotesRepo`, which is a ``Protocol``. That is the
whole point of the layer: the domain states what it needs, and the data layer
decides how to provide it. A test supplies an in-memory repository and never
touches a file.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol, runtime_checkable

UNNAMED = "Untitled"


@dataclass(frozen=True)
class Note:
    """One note. A business entity, not a screen model.

    Attributes:
        id: Stable identity.
        title: Short headline.
        body: The note's text.
    """

    id: int
    title: str = ""
    body: str = ""

    @property
    def label(self) -> str:
        """Return the title, or a placeholder when it has been cleared.

        Returns:
            A title safe to show.
        """
        return self.title or UNNAMED

    def preview(self) -> str:
        """Return the single line a list shows beneath the title.

        Returns:
            The first line of the body, or a placeholder when there is none.
        """
        lines = self.body.strip().splitlines()
        return lines[0] if lines else "No additional text"

    def retitled(self, title: str) -> Note:
        """Return a copy carrying this title.

        Args:
            title: The new headline.

        Returns:
            A new note; this one is unchanged.
        """
        return replace(self, title=title)

    def retexted(self, body: str) -> Note:
        """Return a copy carrying this body.

        Args:
            body: The new text.

        Returns:
            A new note; this one is unchanged.
        """
        return replace(self, body=body)


@runtime_checkable
class NotesRepo(Protocol):
    """What the domain needs from storage, and nothing more.

    Structural, so an in-memory implementation in a test satisfies it exactly as
    well as the file-backed one the app ships with.
    """

    def highest_id(self) -> int:
        """Return the largest identity ever issued, including deleted ones.

        Derived from what is held, this answer drops when a note is deleted, and
        the next note would take the identity the deleted one had -- which is how
        a control left over from before the deletion ends up editing its
        replacement. So the mark is remembered, not recomputed.

        Returns:
            The high-water mark, or zero when nothing was ever issued.
        """
        ...  # pragma: no cover - protocol declaration

    def load(self) -> list[Note]:
        """Return every note held, newest first.

        Returns:
            The stored notes.
        """
        ...  # pragma: no cover - protocol declaration

    def store(self, notes: list[Note]) -> None:
        """Replace everything held.

        Args:
            notes: The notes to keep.
        """
        ...  # pragma: no cover - protocol declaration
