"""One view model per screen: its state, the intents it handles, its behaviour.

A view model holds what its screen needs and changes it in response to
intents. It reaches storage only through the domain's ``Notes``, which the
container hands it, so a test builds one with an in-memory repository.
"""

from notes_app.view_models.note_editor import (
    EditorState,
    EditorViewModel,
    LeaveEditor,
    RemoveNote,
    SetBody,
    SetBodyCaret,
    SetTitle,
    SetTitleCaret,
)
from notes_app.view_models.notes_list import (
    ALL_FILTER,
    TEXT_FILTER,
    DeleteNote,
    ListState,
    ListViewModel,
    NewNote,
    OpenNote,
    SetAbout,
    SetListing,
    SetPreviews,
)

__all__ = [
    "ALL_FILTER",
    "TEXT_FILTER",
    "DeleteNote",
    "EditorState",
    "EditorViewModel",
    "LeaveEditor",
    "ListState",
    "ListViewModel",
    "NewNote",
    "OpenNote",
    "RemoveNote",
    "SetAbout",
    "SetBody",
    "SetBodyCaret",
    "SetListing",
    "SetPreviews",
    "SetTitle",
    "SetTitleCaret",
]
