"""The editor screen: one note's title and text, and the way out."""

from __future__ import annotations

from components import (
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
from components.values import materialIcon

from notes_app.view_models import (
    EditorState,
    LeaveEditor,
    RemoveNote,
    SetBody,
    SetBodyCaret,
    SetTitle,
    SetTitleCaret,
)
from pycompose import composable
from pycompose.ui import Node


def editor_screen(state: EditorState) -> Node:
    """Render the editor for one note.

    Both fields bind the note's id, so a keystroke from a field drawn for
    another note cannot write into this one.

    Args:
        state: The editor's state.

    Returns:
        A Scaffold declaration holding the note's title and body fields, or
        word that the note is gone.
    """
    note = state.note
    if note is None:
        # Restored onto a note deleted since; the back button still leaves.
        return Scaffold(
            top_bar=back_bar(title="Note deleted"),
            content=Column(
                modifier=Modifier().padding(20).fill_max_width(),
                children=[Text(text="This note no longer exists.")],
            ),
        )
    return Scaffold(
        top_bar=back_bar(title=note.label),
        content=Column(
            modifier=Modifier().padding(20).fill_max_width(),
            children=[
                Spacer(modifier=Modifier().size(16)),
                TextField(
                    value=note.title,
                    label="Title",
                    selection=state.title_caret,
                    on_value_change=SetTitle.bind(note_id=note.id),
                    on_selection_change=SetTitleCaret,
                    modifier=Modifier().fill_max_width(),
                ),
                Spacer(modifier=Modifier().size(12)),
                TextField(
                    value=note.body,
                    label="Note",
                    selection=state.body_caret,
                    on_value_change=SetBody.bind(note_id=note.id),
                    on_selection_change=SetBodyCaret,
                    modifier=Modifier().fill_max_width(),
                ),
                Spacer(modifier=Modifier().size(24)),
                TextButton(
                    text="Delete note",
                    on_click=RemoveNote(note_id=note.id),
                ),
            ],
        ),
    )


@composable
def back_bar(*, title: str) -> Node:
    """Render the bar holding the way back and the screen's title.

    Args:
        title: What the bar names.

    Returns:
        A Row declaration.
    """
    return Row(
        vertical_alignment="centerVertically",
        children=[
            IconButton(
                on_click=LeaveEditor(),
                children=[
                    Icon(
                        image_vector=materialIcon(name="AutoMirrored.Filled.ArrowBack"),
                        content_description="Back to notes",
                    )
                ],
            ),
            VerticalDivider(modifier=Modifier().size(1, 24)),
            Spacer(modifier=Modifier().size(8)),
            Text(
                text=title,
                style="titleMedium",
                modifier=Modifier().fill_max_width(0.7),
            ),
        ],
    )
