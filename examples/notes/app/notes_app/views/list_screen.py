"""The list screen: every note, and the commands that act on them."""

from __future__ import annotations

from m3 import (
    Card,
    Column,
    FloatingActionButton,
    HorizontalDivider,
    Icon,
    LazyColumn,
    LinearProgressIndicator,
    ModalBottomSheet,
    Modifier,
    NavigationBar,
    NavigationBarItem,
    Row,
    Scaffold,
    Spacer,
    Switch,
    Text,
    TextButton,
)
from m3.values import Dp, PaddingValues, materialIcon

from notes_app.actions import (
    delete_note,
    new_note,
    open_note,
    set_about,
    set_listing,
    set_previews,
)
from notes_app.domain.models import Note
from notes_app.domain.usecases import carrying_text, count_line, filled_share
from notes_app.state import ALL_FILTER, TEXT_FILTER, Session
from notes_app.theme import Theme
from pycompose import composable
from pycompose.core import Node


@composable
def list_screen(*, notes: list[Note], session: Session) -> Node:
    """Render the whole list screen.

    Args:
        notes: The notes to render, newest first.
        session: The session shell, for the palette and the controls' own state.

    Returns:
        A Scaffold declaration listing every note.
    """
    theme = Theme.of(session)
    listed = carrying_text(notes) if session.listing == TEXT_FILTER else notes
    # The list is data: the host asks for the window it shows, so a thousand
    # notes cost what is on screen.
    body: Node = (
        LazyColumn(
            items=listed,
            key=lambda note: f"row_{note.id}",
            item=lambda note: note_row(
                note=note, previews=session.previews, theme=theme
            ),
            modifier=Modifier().fill_max_width(),
        )
        if listed
        else Text(
            text="No notes yet." if not notes else "No notes with text yet.",
            style="bodyMedium",
            color=theme.muted,
        )
    )
    return Scaffold(
        container_color=theme.background,
        floating_action_button=[new_note_button(theme=theme)],
        bottom_bar=[listing_bar(session=session)],
        content=Column(
            modifier=Modifier().padding(20).fill_max_width(),
            children=[
                Text(text="Notes", style="titleLarge", color=theme.on_surface),
                Text(text=count_line(listed), style="bodySmall", color=theme.muted),
                Spacer(modifier=Modifier().size(8)),
                previews_row(session=session, theme=theme),
                Spacer(modifier=Modifier().size(8)),
                TextButton(
                    text="How this works", on_click=set_about.with_args(open=True)
                ),
                Spacer(modifier=Modifier().size(8)),
                HorizontalDivider(thickness=1, color=theme.muted),
                Spacer(modifier=Modifier().size(12)),
                body,
                about_sheet(session=session, theme=theme, notes=notes),
            ],
        ),
    )


@composable
def new_note_button(*, theme: Theme) -> Node:
    """Render the screen's one accented command.

    A floating action button is Material's shape for "create", and the icon
    inside it is the whole label.

    Args:
        theme: Colours to paint with.

    Returns:
        The FloatingActionButton declaration.
    """
    return FloatingActionButton(
        on_click=new_note,
        container_color=theme.primary,
        children=[
            Icon(
                image_vector=materialIcon(name="Filled.Add"),
                content_description="New note",
                tint=theme.background,
            )
        ],
    )


@composable
def previews_row(*, session: Session, theme: Theme) -> Node:
    """Render the switch that decides whether rows show a line of body text.

    The switch owns its checked state on the native side and reports what it
    settled on; Python states the desired value in the snapshot. The label tells
    screen readers what the switch is for, since a bare switch reads as nothing.

    Args:
        session: The session shell, which holds whether previews are shown.
        theme: Colours to paint with.

    Returns:
        A Row pairing the label with the Switch.
    """
    return Row(
        vertical_alignment="center",
        children=[
            Text(text="Show note previews", style="bodyMedium", color=theme.muted),
            Spacer(modifier=Modifier().size(8)),
            Switch(checked=session.previews, on_checked_change=set_previews),
            Spacer(modifier=Modifier().size(8)),
        ],
    )


@composable
def listing_bar(*, session: Session) -> Node:
    """Render the bar that filters the list.

    Each item names the filter it stands for in the binding, so one transition
    serves both items and the selected item is the session's choice read back.
    The icons sit in the item's own slot, so the host composes them where the
    bar puts them; the labels below them are the whole name of each filter.

    Args:
        session: The session shell, which holds the filter in force.

    Returns:
        The NavigationBar declaration.
    """
    return NavigationBar(
        children=[
            NavigationBarItem(
                selected=session.listing == ALL_FILTER,
                on_click=set_listing.with_args(value=ALL_FILTER),
                icon=[
                    Icon(
                        image_vector=materialIcon(name="Filled.Home"),
                        content_description=None,
                    )
                ],
                label=[Text(text="All notes")],
            ),
            NavigationBarItem(
                selected=session.listing == TEXT_FILTER,
                on_click=set_listing.with_args(value=TEXT_FILTER),
                icon=[
                    Icon(
                        image_vector=materialIcon(name="Filled.Edit"),
                        content_description=None,
                    )
                ],
                label=[Text(text="With text")],
            ),
        ],
    )


@composable
def about_sheet(*, session: Session, theme: Theme, notes: list[Note]) -> Node:
    """Render the sheet explaining what the app is and how it is built.

    Args:
        session: The session shell, which holds whether the sheet is open.
        theme: Colours to paint with.
        notes: The notes the bar inside the sheet measures.

    Returns:
        The ModalBottomSheet declaration.
    """
    return ModalBottomSheet(
        open=session.about_open,
        on_open_change=set_about,
        children=[
            Column(
                modifier=Modifier().padding(20).fill_max_width(),
                children=[
                    Row(
                        vertical_alignment="center",
                        children=[
                            Icon(
                                image_vector=materialIcon(name="Filled.Info"),
                                content_description="About this app",
                                tint=theme.primary,
                            ),
                            Spacer(modifier=Modifier().size(8)),
                            Text(
                                text="How this works",
                                style="titleMedium",
                                color=theme.on_surface,
                            ),
                        ],
                    ),
                    Spacer(modifier=Modifier().size(8)),
                    Text(
                        text=(
                            "Every control here is native Material 3. "
                            "Python states whether this sheet is open; "
                            "the host drives it and reports back what "
                            "it settled on."
                        ),
                        style="bodyMedium",
                        color=theme.muted,
                    ),
                    Spacer(modifier=Modifier().size(12)),
                    LinearProgressIndicator(progress=filled_share(notes)),
                    Spacer(modifier=Modifier().size(8)),
                    Text(
                        text=(
                            "That bar is Python state too: the share of "
                            "your notes that have a body. The value is "
                            "read during composition, so it tracks the "
                            "notes you keep."
                        ),
                        style="bodySmall",
                        color=theme.muted,
                    ),
                    Spacer(modifier=Modifier().size(12)),
                    TextButton(text="Got it", on_click=set_about.with_args(open=False)),
                ],
            ),
        ],
    )


@composable
def note_row(*, note: Note, previews: bool, theme: Theme) -> Node:
    """Render one row: the note's title and preview, plus its delete control.

    The card itself opens the note, which is what a user expects from a list,
    and the delete control sits inside it with its own binding: Compose gives
    the innermost clickable the tap. The binding carries the note's id, so one
    Python transition serves every row on screen without the host ever holding
    a handler.

    Args:
        note: The note this row shows.
        previews: Whether the row shows the note's preview line.
        theme: Colours to paint with.

    Returns:
        A clickable Card carrying this note's bindings.
    """
    caption: list[Node] = [
        Text(text=note.label, style="titleMedium", color=theme.on_surface)
    ]
    if previews:
        caption.append(Text(text=note.preview(), style="bodySmall", color=theme.muted))
    return Card(
        on_click=open_note.with_args(note_id=note.id),
        modifier=Modifier().padding(PaddingValues(bottom=Dp(8))).fill_max_width(),
        children=[
            Row(
                vertical_alignment="center",
                modifier=Modifier().padding(10),
                children=[
                    Column(modifier=Modifier().fill_max_width(0.75), children=caption),
                    TextButton(
                        text="Delete", on_click=delete_note.with_args(note_id=note.id)
                    ),
                ],
            )
        ],
    )
