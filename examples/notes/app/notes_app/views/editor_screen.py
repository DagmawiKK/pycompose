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

from notes_app.domain.models import Note
from notes_app.state import Session
from notes_app.theme import Theme
from pycompose import Registry, composable
from pycompose.core import Node


@composable
def editor_screen(
    *,
    note: Note,
    session: Session,
    actions: Registry,
) -> Node:
    """Render the editor for one note.

    Both fields bind the same note id, so a keystroke resolves to the note being
    edited without the view knowing anything about which note that is.

    Args:
        note: The note being edited.
        session: The session shell, for the palette.
        actions: The registry this screen binds its controls to. Callers omit
            it; the app context supplies it, as Compose supplies
            ``LocalConfiguration.current``.

    Returns:
        A Scaffold declaration holding the note's title and body fields.
    """
    theme = Theme.of(session)
    return Scaffold(
        id="screen",
        container_color=theme.background,
        top_bar=Row(
            id="bar",
            vertical_alignment="center",
            children=[
                IconButton(
                    id="back",
                    on_click=actions.go_back.bind(id="back"),
                    children=[
                        Icon(
                            id="back_icon",
                            image_vector=materialIcon(
                                name="AutoMirrored.Filled.ArrowBack"
                            ),
                            content_description="Back to notes",
                            tint=theme.on_surface,
                        )
                    ],
                ),
                VerticalDivider(
                    id="bar_rule",
                    color=theme.muted,
                    modifier=Modifier().size(1, 24),
                ),
                Spacer(id="gap_bar_title", modifier=Modifier().size(8)),
                Text(
                    id="bar_title",
                    text=note.label,
                    style="titleMedium",
                    color=theme.on_surface,
                    modifier=Modifier().fill_max_width(0.7),
                ),
            ],
        ),
        content=Column(
            id="body",
            modifier=Modifier().padding(20).fill_max_width(),
            children=[
                Spacer(id="gap_title", modifier=Modifier().size(16)),
                TextField(
                    id="title_field",
                    value=note.title,
                    label="Title",
                    selection=session.title_caret,
                    on_value_change=actions.set_title.bind(id="title", note_id=note.id),
                    on_selection_change=actions.set_title_caret.bind(
                        id="title", note_id=note.id
                    ),
                    modifier=Modifier().fill_max_width(),
                ),
                Spacer(id="gap_body", modifier=Modifier().size(12)),
                TextField(
                    id="body_field",
                    value=note.body,
                    label="Note",
                    selection=session.body_caret,
                    on_value_change=actions.set_body.bind(id="body", note_id=note.id),
                    on_selection_change=actions.set_body_caret.bind(
                        id="body", note_id=note.id
                    ),
                    modifier=Modifier().fill_max_width(),
                ),
                Spacer(id="gap_delete", modifier=Modifier().size(24)),
                TextButton(
                    id="delete",
                    text="Delete note",
                    on_click=actions.delete_note.bind(id="editor", note_id=note.id),
                ),
            ],
        ),
    )
