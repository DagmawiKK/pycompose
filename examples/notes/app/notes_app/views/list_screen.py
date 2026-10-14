"""The list screen: every note, and the commands that act on them."""

from __future__ import annotations

from m3 import (
    Button,
    Column,
    LazyColumn,
    Modifier,
    Row,
    Scaffold,
    Spacer,
    Text,
    TextButton,
)

from notes_app.domain.models import Note
from notes_app.domain.usecases import count_line
from notes_app.state import Session
from notes_app.theme import Theme
from pycompose import Registry, composable
from pycompose.core import Node


@composable
def list_screen(
    *,
    notes: list[Note],
    session: Session,
    actions: Registry,
) -> Node:
    """Render the whole list screen.

    Args:
        notes: The notes to render, newest first.
        session: The session shell, for the palette.
        actions: The registry this screen binds its controls to. Callers omit
            it; the app context supplies it, as Compose supplies
            ``LocalConfiguration.current``.

    Returns:
        A Scaffold declaration listing every note.
    """
    theme = Theme.of(session)
    rows: list[Node] = [
        note_row(id=f"row_{note.id}", note=note, theme=theme, actions=actions)
        for note in notes
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
                    text=count_line(notes),
                    style="bodySmall",
                    color=theme.muted,
                ),
                Spacer(id="gap_commands", modifier=Modifier().size(12)),
                Row(
                    id="commands",
                    vertical_alignment="center",
                    children=[
                        Button(
                            id="new",
                            text="New note",
                            on_click=actions.new_note.bind(id="new"),
                        ),
                        Spacer(id="gap_about", modifier=Modifier().size(8)),
                        TextButton(
                            id="about",
                            text="How this works",
                            on_click=actions.show_about.bind(id="about"),
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
    actions: Registry,
) -> Node:
    """Render one row: the note's title and preview, plus its delete control.

    The whole row opens the note, which is what a user expects from a list. The
    delete control carries the same bound id, so one Python transition serves every
    row on screen without the host ever holding a handler.

    Args:
        note: The note this row shows.
        theme: Colours to paint with.
        actions: The registry this screen binds its controls to. Callers omit
            it; the app context supplies it, as Compose supplies
            ``LocalConfiguration.current``.

    Returns:
        A clickable Row carrying this note's bindings.
    """
    return Row(
        id="row",
        vertical_alignment="center",
        modifier=Modifier()
        .padding(10)
        .clickable(actions.open_note.bind(id=f"n{note.id}", note_id=note.id)),
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
                on_click=actions.delete_note.bind(id=f"n{note.id}", note_id=note.id),
            ),
        ],
    )
