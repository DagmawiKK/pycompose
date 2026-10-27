"""The editor screen: one note's title and text, and the way out."""

from __future__ import annotations

from m3 import (
    Column,
    Icon,
    IconButton,
    Modifier,
    Row,
    Scaffold,
    Spacer,
    Text,
    TextButton,
    TextField,
    VerticalDivider,
)
from m3.values import materialIcon

from notes_app.actions import (
    delete_note,
    go_back,
    set_body,
    set_body_caret,
    set_title,
    set_title_caret,
)
from notes_app.domain.models import Note
from notes_app.state import Session
from pycompose import composable
from pycompose.core import Node


@composable
def editor_screen(*, note: Note, session: Session) -> Node:
    """Render the editor for one note.

    Both fields bind the same note id, so a keystroke resolves to the note being
    edited without the view knowing anything about which note that is.

    Args:
        note: The note being edited.
        session: The session shell, for the carets.

    Returns:
        A Scaffold declaration holding the note's title and body fields.
    """
    return Scaffold(
        top_bar=Row(
            vertical_alignment="center",
            children=[
                IconButton(
                    on_click=go_back,
                    children=[
                        Icon(
                            image_vector=materialIcon(
                                name="AutoMirrored.Filled.ArrowBack"
                            ),
                            content_description="Back to notes",
                        )
                    ],
                ),
                VerticalDivider(modifier=Modifier().size(1, 24)),
                Spacer(modifier=Modifier().size(8)),
                Text(
                    text=note.label,
                    style="titleMedium",
                    modifier=Modifier().fill_max_width(0.7),
                ),
            ],
        ),
        content=Column(
            modifier=Modifier().padding(20).fill_max_width(),
            children=[
                Spacer(modifier=Modifier().size(16)),
                TextField(
                    value=note.title,
                    label="Title",
                    selection=session.title_caret,
                    on_value_change=set_title.with_args(note_id=note.id),
                    on_selection_change=set_title_caret,
                    modifier=Modifier().fill_max_width(),
                ),
                Spacer(modifier=Modifier().size(12)),
                TextField(
                    value=note.body,
                    label="Note",
                    selection=session.body_caret,
                    on_value_change=set_body.with_args(note_id=note.id),
                    on_selection_change=set_body_caret,
                    modifier=Modifier().fill_max_width(),
                ),
                Spacer(modifier=Modifier().size(24)),
                TextButton(
                    text="Delete note",
                    on_click=delete_note.with_args(note_id=note.id),
                ),
            ],
        ),
    )
