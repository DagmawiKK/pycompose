"""The editor screen's view model: one note's title and text, and the way out."""

from __future__ import annotations

from notes_app.domain import Note, Notes
from pycompose.app import Haptic, Intent, Pop, ViewModel
from pycompose.state import AppState, Loaded


class EditorState(AppState):
    """What the editor shows.

    Attributes:
        note_id: The note being edited.
        note: The note as stored, or None once it is gone; never saved.
        title_caret: Where the caret sits in the title field.
        body_caret: Where the caret sits in the body field.
    """

    note_id: int
    note: Loaded[Note | None] = None
    title_caret: int = 0
    body_caret: int = 0


class SetTitle(Intent):
    """Record the title field's text.

    Attributes:
        note_id: The note the field edits.
        value: The field's text, supplied by the event.
    """

    note_id: int
    value: str


class SetBody(Intent):
    """Record the body field's text.

    Attributes:
        note_id: The note the field edits.
        value: The field's text, supplied by the event.
    """

    note_id: int
    value: str


class SetTitleCaret(Intent):
    """Record where the caret sits in the title.

    The field is controlled, so without the caret in the snapshot the next
    keystroke would move it from where the user left it.

    Attributes:
        value: Where the caret sits, supplied by the event.
    """

    value: int


class SetBodyCaret(Intent):
    """Record where the caret sits in the body.

    Attributes:
        value: Where the caret sits, supplied by the event.
    """

    value: int


class RemoveNote(Intent):
    """Delete the note being edited and return to the list.

    Attributes:
        note_id: The note the control was drawn for.
    """

    note_id: int


class LeaveEditor(Intent):
    """Return to the list."""


class EditorViewModel(ViewModel[EditorState]):
    """One note being edited.

    Edits go straight to the repository, so nothing is lost when the process
    dies; the state keeps only the carets and which note this is.

    Args:
        notes: What the app can do with notes.
        note_id: The note to edit.
    """

    def __init__(self, notes: Notes, note_id: int) -> None:
        super().__init__(EditorState(note_id=note_id, note=notes.get(note_id)))
        self._notes = notes

    def _reload(self) -> None:
        self.state = self.state.evolve(note=self._notes.get(self.state.note_id))

    def on_intent(self, intent: Intent) -> None:
        """Handle one intent from the editor.

        An edit bound to another note is left alone: a stale control must be
        harmless rather than write into the wrong note.

        Args:
            intent: What the control asked for.
        """
        mine = self.state.note is not None
        match intent:
            case SetTitle(note_id=self.state.note_id, value=value) if mine:
                self._notes.rename(self.state.note_id, value)
                self._reload()
            case SetBody(note_id=self.state.note_id, value=value) if mine:
                self._notes.retext(self.state.note_id, value)
                self._reload()
            case SetTitleCaret(value=value):
                self.state = self.state.evolve(title_caret=value)
            case SetBodyCaret(value=value):
                self.state = self.state.evolve(body_caret=value)
            case RemoveNote(note_id=self.state.note_id) if mine:
                self._notes.delete(self.state.note_id)
                self.emit(Haptic())
                self.navigate(Pop())
            case LeaveEditor():
                self.navigate(Pop())
            case _:
                # An intent from a screen that is no longer showing.
                pass
