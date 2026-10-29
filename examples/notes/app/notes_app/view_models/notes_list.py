"""The list screen's view model: every note, and the commands that act on them."""

from __future__ import annotations

from notes_app.domain import Note, Notes
from notes_app.routes import EditorRoute
from pycompose.app import Haptic, Intent, Push, StateFlow, ViewModel
from pycompose.state import AppState, Loaded

TEXT_FILTER = "with_text"
"""The listing that keeps only the notes carrying a body."""

ALL_FILTER = "all"
"""The listing that keeps every note."""


class ListState(AppState):
    """What the list screen shows.

    Attributes:
        notes: Every note, newest first; read from storage, never saved.
        about_open: Whether the about sheet is showing.
        previews: Whether rows show a line of the note's body.
        listing: Which filter the list is showing.
    """

    notes: Loaded[tuple[Note, ...]] = ()
    about_open: bool = False
    previews: bool = True
    listing: str = ALL_FILTER


class NewNote(Intent):
    """Create a note and open it."""


class OpenNote(Intent):
    """Open one note's editor.

    Attributes:
        note_id: The note the row shows.
    """

    note_id: int


class DeleteNote(Intent):
    """Delete one note.

    Attributes:
        note_id: The note the row shows.
    """

    note_id: int


class SetAbout(Intent):
    """Show or hide the about sheet.

    The sheet reports what it settled on through this same intent, so one
    intent serves the buttons and the swipe that dismisses it.

    Attributes:
        open: The visibility the control or the sheet stated.
    """

    open: bool


class SetPreviews(Intent):
    """Show or hide each row's line of body text.

    Attributes:
        value: The value the switch settled on.
    """

    value: bool


class SetListing(Intent):
    """Show every note, or only the ones carrying text.

    Attributes:
        value: The filter the tapped item stands for. A value the screen does
            not know shows the whole list rather than an empty one.
    """

    value: str


class ListViewModel(ViewModel[ListState]):
    """The list of notes and what the user can do with it.

    It follows the repository's listing for as long as it lives, so edits made
    on the editor are on the list when the user comes back to it.

    Args:
        notes: What the app can do with notes.
        listing: Every note, newest first, as the repository changes it.
    """

    def __init__(self, notes: Notes, listing: StateFlow[tuple[Note, ...]]) -> None:
        super().__init__(ListState(notes=listing.value))
        self._notes = notes
        self._listing = listing
        self.launch(self._follow())

    async def _follow(self) -> None:
        async for notes in self._listing:
            self._show(notes)

    def _show(self, notes: tuple[Note, ...]) -> None:
        if notes != self.state.notes:
            self.state = self.state.evolve(notes=notes)

    def on_intent(self, intent: Intent) -> None:
        """Handle one intent from the list screen.

        A note that is gone by the time its row is tapped is left alone: the
        row outlived it, and acting on its id must do nothing.

        Args:
            intent: What the control asked for.
        """
        match intent:
            case NewNote():
                note_id = self._notes.create()
                self.emit(Haptic())
                self.navigate(Push(EditorRoute(note_id=note_id)))
            case OpenNote(note_id=note_id) if self._notes.get(note_id) is not None:
                self.navigate(Push(EditorRoute(note_id=note_id)))
            case DeleteNote(note_id=note_id) if self._notes.get(note_id) is not None:
                self._notes.delete(note_id)
                self.emit(Haptic())
                # The screen shows the deletion in this snapshot, not the next.
                self._show(self._listing.value)
            case SetAbout(open=open_):
                self.state = self.state.evolve(about_open=open_)
            case SetPreviews(value=value):
                self.state = self.state.evolve(previews=value)
            case SetListing(value=value):
                self.state = self.state.evolve(listing=value)
            case _:
                # An intent from a screen that is no longer showing.
                pass
