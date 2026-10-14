"""The list screen: every note, and the commands that act on them."""

from __future__ import annotations

from notes_app.handlers import Handlers
from notes_app.state import Note, NotesState, Session
from notes_app.theme import Theme
from pycompose import composable
from pycompose.core import Node
from pycompose.m3 import (
    Column,
    FilledButton,
    LazyColumn,
    Modifier,
    Row,
    Scaffold,
    Spacer,
    Text,
    TextButton,
)


@composable
def list_screen(
    *,
    state: NotesState,
    session: Session,
    handlers: Handlers,
) -> Node:
    """Render the whole list screen.

    Args:
        state: The notes partition.
        session: The session shell, for the palette.
        handlers: Action references this screen binds to.

    Returns:
        A Scaffold declaration listing every note.
    """
    theme = Theme.of(session)
    rows: list[Node] = [
        note_row(id=f"row_{note.id}", note=note, theme=theme, handlers=handlers)
        for note in state.notes
    ]
    if not rows:
        rows = [
            Text(
                id="empty",
                text="No notes yet.",
                style="bodyMedium",
                color=theme.muted,
            )
        ]
    return Scaffold(
        id="screen",
        container_color=theme.background,
        content=Column(
            id="body",
            modifier=Modifier().padding(20).fill_max_width(),
            children=[
                Text(
                    id="title",
                    text="Notes",
                    style="titleLarge",
                    color=theme.on_surface,
                ),
                Text(
                    id="count",
                    text=state.count_line(),
                    style="bodySmall",
                    color=theme.muted,
                ),
                Spacer(id="gap_commands", modifier=Modifier().size(12)),
                Row(
                    id="commands",
                    vertical_alignment="center",
                    children=[
                        FilledButton(
                            id="new",
                            text="New note",
                            on_click=handlers.new_note.bind(id="new"),
                        ),
                        Spacer(id="gap_about", modifier=Modifier().size(8)),
                        TextButton(
                            id="about",
                            text="How this works",
                            on_click=handlers.show_about.bind(id="about"),
                        ),
                    ],
                ),
                Spacer(id="gap_list", modifier=Modifier().size(16)),
                LazyColumn(
                    id="notes",
                    items=rows,
                    modifier=Modifier().fill_max_width(),
                ),
            ],
        ),
    )


@composable
def note_row(
    *,
    note: Note,
    theme: Theme,
    handlers: Handlers,
) -> Node:
    """Render one row: the note's title and preview, plus its delete control.

    The whole row opens the note, which is what a user expects from a list. The
    delete control carries the same bound id, so one Python transition serves every
    row on screen without the host ever holding a handler.

    Args:
        note: The note this row shows.
        theme: Colours to paint with.
        handlers: Action references this screen binds to.

    Returns:
        A clickable Row carrying this note's bindings.
    """
    return Row(
        id="row",
        vertical_alignment="center",
        modifier=Modifier()
        .padding(10)
        .clickable(handlers.open_note.bind(id=f"n{note.id}", note_id=note.id)),
        children=[
            Column(
                id="text",
                modifier=Modifier().fill_max_width(0.75),
                children=[
                    Text(
                        id="title",
                        text=note.label,
                        style="titleMedium",
                        color=theme.on_surface,
                    ),
                    Text(
                        id="preview",
                        text=note.preview(),
                        style="bodySmall",
                        color=theme.muted,
                    ),
                ],
            ),
            TextButton(
                id="delete",
                text="Delete",
                on_click=handlers.delete_note.bind(id=f"n{note.id}", note_id=note.id),
            ),
        ],
    )
