"""The app's state, declared rather than hand-encoded.

``AppState`` is what a Kotlin app gets from ``@Serializable``: the codec is
derived from the declaration, so there is no ``encode`` to write and no ``decode``
to keep in step with it.

Three fields, because three different things need to survive:

* ``notes`` — the app's own data.
* ``route`` — which screen is showing. The host owns this, but an action still
  needs it to render the snapshot that follows a tap.
* ``dark`` — a fact about the device Python cannot observe, so the app has to
  remember it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from pycompose.state import AppState

LIST_ROUTE = "notes"
DETAIL_PREFIX = "note:"


def detail_route(note_id: int) -> str:
    """Return the route naming one note.

    Args:
        note_id: Identity the route should address.

    Returns:
        The detail route.
    """
    return f"{DETAIL_PREFIX}{note_id}"


def note_in(route: str) -> int | None:
    """Return the note id a route addresses.

    Args:
        route: The route being shown.

    Returns:
        The note id, or None when the route is the list or is not a note route.
    """
    if not route.startswith(DETAIL_PREFIX):
        return None
    raw = route.removeprefix(DETAIL_PREFIX)
    return int(raw) if raw.isdigit() else None


@dataclass(frozen=True)
class Note:
    """One note.

    A plain dataclass rather than declared state: it has no codec of its own, it
    simply travels inside the notes list.

    Attributes:
        id: Stable identity. Used for per-row action bindings and in detail routes.
        title: Short headline, shown in the list and as the editor's title field.
        body: The note's text.
    """

    id: int
    title: str = ""
    body: str = ""

    @property
    def label(self) -> str:
        """Return the title, or a placeholder when it has been cleared.

        Returns:
            A title safe to show in a list row or a screen bar.
        """
        return self.title or "Untitled"

    def preview(self) -> str:
        """Return the single line the list shows beneath the title.

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


class Session(AppState):
    """The session shell: the small state every screen needs.

    Kept apart from the notes on purpose. This is the part small enough to hand
    to the host on every snapshot and to restore after process death, and it is
    the only part the host has to keep while fifteen screens come and go.

    Attributes:
        route: Which screen is showing.
        dark: Whether the device is in dark mode.
    """

    route: str = LIST_ROUTE
    dark: bool = False


class NotesState(AppState):
    """The notes feature: its own state, carried as one partition.

    Attached only while a screen actually shows notes, so typing in a note does
    not re-encode whatever the other fourteen features are holding.

    Attributes:
        notes: Every note, newest first.
        next_id: The id the next created note will take.
    """

    notes: tuple[Note, ...] = ()
    next_id: int = 1

    # -- queries ----------------------------------------------------------

    def find(self, note_id: int) -> Note | None:
        """Return the note with this id, when the app holds it.

        Args:
            note_id: Identity to look up.

        Returns:
            The matching note, or None.
        """
        return next((note for note in self.notes if note.id == note_id), None)

    def count_line(self) -> str:
        """Return the line describing how much the app holds.

        Returns:
            A short, correctly pluralised count.
        """
        total = len(self.notes)
        return f"{total} note{'s' if total != 1 else ''}"

    # -- transitions ------------------------------------------------------

    def retitled(self, note_id: int, title: str) -> NotesState:
        """Return a copy with one note retitled.

        Args:
            note_id: Identity of the note to change.
            title: Its new headline.

        Returns:
            A new state.
        """
        return self._edited(note_id, lambda note: note.retitled(title))

    def retexted(self, note_id: int, body: str) -> NotesState:
        """Return a copy with one note's text replaced.

        Args:
            note_id: Identity of the note to change.
            body: Its new text.

        Returns:
            A new state.
        """
        return self._edited(note_id, lambda note: note.retexted(body))

    def _edited(self, note_id: int, change: Callable[[Note], Note]) -> NotesState:
        """Return a copy with one note replaced.

        Args:
            note_id: Identity of the note to change.
            change: Callable producing the edited note.

        Returns:
            A new state.
        """
        found = self.find(note_id)
        if found is None:
            return self
        return self.evolve(
            notes=tuple(
                change(note) if note.id == note_id else note for note in self.notes
            )
        )

    def created(self) -> tuple[NotesState, int]:
        """Return a copy holding a new note, and the id it took.

        Returns:
            The updated state and the new note's id.
        """
        note = Note(id=self.next_id, title="", body="")
        return self.evolve(notes=(note, *self.notes), next_id=self.next_id + 1), note.id

    def deleted(self, note_id: int) -> NotesState:
        """Return a copy without one note.

        Args:
            note_id: Identity to drop.

        Returns:
            A new state; the original is unchanged when the note is not present.
        """
        return self.evolve(
            notes=tuple(note for note in self.notes if note.id != note_id)
        )

    def showing(self, route: str) -> NotesState:
        """Return a copy on another route.

        Args:
            route: The route to move to.

        Returns:
            A new state on that route.
        """
        return self.evolve(route=route)


def seeded_session() -> Session:
    """Return the shell a genuinely fresh install starts from.

    Returns:
        A session on the list, in light mode.
    """
    return Session()


def seeded() -> NotesState:
    """Return the notes a genuinely fresh install starts from.

    Returns:
        Two notes, so a first run shows a populated list rather than a void.
    """
    return NotesState(
        notes=(
            Note(
                id=1,
                title="Welcome",
                body=(
                    "This app is written entirely in Python.\n"
                    "Every control here is a native Material 3 composable."
                ),
            ),
            Note(
                id=2,
                title="Try it",
                body="Tap a note to edit it, or add one with the New button.",
            ),
        ),
        next_id=3,
    )
