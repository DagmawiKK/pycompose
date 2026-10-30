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
from m3.values import Dp, PaddingValues, ThemeColor, materialIcon

from notes_app.domain.models import Note
from notes_app.domain.usecases import carrying_text, count_line, filled_share
from notes_app.view_models import (
    ALL_FILTER,
    TEXT_FILTER,
    DeleteNote,
    ListState,
    NewNote,
    OpenNote,
    SetAbout,
    SetListing,
    SetPreviews,
)
from pycompose import composable
from pycompose.model.nodes import Node


def list_screen(state: ListState) -> Node:
    """Render the whole list screen.

    Args:
        state: The list's state.

    Returns:
        A Scaffold declaration listing every note.
    """
    notes = list(state.notes)
    listed = carrying_text(notes) if state.listing == TEXT_FILTER else notes
    # The list is data: the host asks for the window it shows, so a thousand
    # notes cost what is on screen.
    body: Node = (
        LazyColumn(
            items=listed,
            key=lambda note: f"row_{note.id}",
            item=lambda note: note_row(note=note, previews=state.previews),
            modifier=Modifier().fill_max_width(),
        )
        if listed
        else Text(
            text="No notes yet." if not notes else "No notes with text yet.",
            style="bodyMedium",
            color=ThemeColor("onSurfaceVariant"),
        )
    )
    return Scaffold(
        floating_action_button=[new_note_button()],
        bottom_bar=[listing_bar(listing=state.listing)],
        content=Column(
            modifier=Modifier().padding(20).fill_max_width(),
            children=[
                Text(text="Notes", style="titleLarge"),
                Text(
                    text=count_line(listed),
                    style="bodySmall",
                    color=ThemeColor("onSurfaceVariant"),
                ),
                Spacer(modifier=Modifier().size(8)),
                previews_row(previews=state.previews),
                Spacer(modifier=Modifier().size(8)),
                TextButton(text="How this works", on_click=SetAbout(open=True)),
                Spacer(modifier=Modifier().size(8)),
                HorizontalDivider(thickness=1),
                Spacer(modifier=Modifier().size(12)),
                body,
                about_sheet(open=state.about_open, notes=notes),
            ],
        ),
    )


@composable
def new_note_button() -> Node:
    """Render the screen's one accented command.

    A floating action button is Material's shape for "create", and the icon
    inside it is the whole label.

    Returns:
        The FloatingActionButton declaration.
    """
    return FloatingActionButton(
        on_click=NewNote(),
        container_color=ThemeColor("primary"),
        children=[
            Icon(
                image_vector=materialIcon(name="Filled.Add"),
                content_description="New note",
                tint=ThemeColor("onPrimary"),
            )
        ],
    )


@composable
def previews_row(*, previews: bool) -> Node:
    """Render the switch that decides whether rows show a line of body text.

    The switch owns its checked state on the native side and reports what it
    settled on; Python states the desired value in the snapshot. The label tells
    screen readers what the switch is for, since a bare switch reads as nothing.

    Args:
        previews: Whether previews are shown.

    Returns:
        A Row pairing the label with the Switch.
    """
    return Row(
        vertical_alignment="centerVertically",
        children=[
            Text(
                text="Show note previews",
                style="bodyMedium",
                color=ThemeColor("onSurfaceVariant"),
            ),
            Spacer(modifier=Modifier().size(8)),
            Switch(checked=previews, on_checked_change=SetPreviews),
            Spacer(modifier=Modifier().size(8)),
        ],
    )


@composable
def listing_bar(*, listing: str) -> Node:
    """Render the bar that filters the list.

    Each item names the filter it stands for in the binding, so one transition
    serves both items and the selected item is the state's choice read back.
    The icons sit in the item's own slot, so the host composes them where the
    bar puts them; the labels below them are the whole name of each filter.

    Args:
        listing: The filter in force.

    Returns:
        The NavigationBar declaration.
    """
    return NavigationBar(
        children=[
            NavigationBarItem(
                selected=listing == ALL_FILTER,
                on_click=SetListing(value=ALL_FILTER),
                icon=[
                    Icon(
                        image_vector=materialIcon(name="Filled.Home"),
                        content_description=None,
                    )
                ],
                label=[Text(text="All notes")],
            ),
            NavigationBarItem(
                selected=listing == TEXT_FILTER,
                on_click=SetListing(value=TEXT_FILTER),
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
def about_sheet(*, open: bool, notes: list[Note]) -> Node:
    """Render the sheet explaining what the app is and how it is built.

    Args:
        open: Whether the sheet is open.
        notes: The notes the bar inside the sheet measures.

    Returns:
        The ModalBottomSheet declaration.
    """
    return ModalBottomSheet(
        open=open,
        on_open_change=SetAbout,
        children=[
            Column(
                modifier=Modifier().padding(20).fill_max_width(),
                children=[
                    Row(
                        vertical_alignment="centerVertically",
                        children=[
                            Icon(
                                image_vector=materialIcon(name="Filled.Info"),
                                content_description="About this app",
                                tint=ThemeColor("primary"),
                            ),
                            Spacer(modifier=Modifier().size(8)),
                            Text(
                                text="How this works",
                                style="titleMedium",
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
                        color=ThemeColor("onSurfaceVariant"),
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
                        color=ThemeColor("onSurfaceVariant"),
                    ),
                    Spacer(modifier=Modifier().size(12)),
                    TextButton(text="Got it", on_click=SetAbout(open=False)),
                ],
            ),
        ],
    )


@composable
def note_row(*, note: Note, previews: bool) -> Node:
    """Render one row: the note's title and preview, plus its delete control.

    The card itself opens the note, which is what a user expects from a list,
    and the delete control sits inside it with its own binding: Compose gives
    the innermost clickable the tap. The binding carries the note's id, so one
    view model intent serves every row on screen without the host ever holding
    a handler.

    Args:
        note: The note this row shows.
        previews: Whether the row shows the note's preview line.

    Returns:
        A clickable Card carrying this note's bindings.
    """
    caption: list[Node] = [Text(text=note.label, style="titleMedium")]
    if previews:
        caption.append(
            Text(
                text=note.preview(),
                style="bodySmall",
                color=ThemeColor("onSurfaceVariant"),
            )
        )
    return Card(
        on_click=OpenNote(note_id=note.id),
        modifier=Modifier().padding(PaddingValues(bottom=Dp(8))).fill_max_width(),
        children=[
            Row(
                vertical_alignment="centerVertically",
                modifier=Modifier().padding(10),
                children=[
                    Column(modifier=Modifier().fill_max_width(0.75), children=caption),
                    TextButton(text="Delete", on_click=DeleteNote(note_id=note.id)),
                ],
            )
        ],
    )
