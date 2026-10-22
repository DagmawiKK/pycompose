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

from notes_app.domain.models import Note
from notes_app.domain.usecases import carrying_text, count_line, filled_share
from notes_app.state import ALL_FILTER, TEXT_FILTER, Session
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
        session: The session shell, for the palette and the controls' own state.
        actions: The registry this screen binds its controls to. Callers omit
            it; the app context supplies it, as Compose supplies
            ``LocalConfiguration.current``.

    Returns:
        A Scaffold declaration listing every note.
    """
    theme = Theme.of(session)
    listed = carrying_text(notes) if session.listing == TEXT_FILTER else notes
    rows: list[Node] = [
        note_row(
            id=f"row_{note.id}",
            note=note,
            previews=session.previews,
            theme=theme,
            actions=actions,
        )
        for note in listed
    ]
    if not rows:
        rows = [
            Text(
                id="empty",
                text="No notes yet." if not notes else "No notes with text yet.",
                style="bodyMedium",
                color=theme.muted,
            )
        ]
    return Scaffold(
        id="screen",
        container_color=theme.background,
        floating_action_button=[
            new_note_button(id="new_button", theme=theme, actions=actions),
        ],
        bottom_bar=[listing_bar(id="listing", session=session, actions=actions)],
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
                    text=count_line(listed),
                    style="bodySmall",
                    color=theme.muted,
                ),
                Spacer(id="gap_previews", modifier=Modifier().size(8)),
                previews_row(
                    id="previews_row", session=session, theme=theme, actions=actions
                ),
                Spacer(id="gap_about", modifier=Modifier().size(8)),
                TextButton(
                    id="about",
                    text="How this works",
                    on_click=actions.set_about.bind(id="about", open=True),
                ),
                Spacer(id="gap_rule", modifier=Modifier().size(8)),
                HorizontalDivider(
                    id="rule",
                    thickness=1,
                    color=theme.muted,
                ),
                Spacer(id="gap_list", modifier=Modifier().size(12)),
                LazyColumn(
                    id="notes",
                    items=rows,
                    modifier=Modifier().fill_max_width(),
                ),
                about_sheet(
                    id="about_sheet",
                    session=session,
                    theme=theme,
                    actions=actions,
                    notes=notes,
                ),
            ],
        ),
    )


@composable
def new_note_button(*, theme: Theme, actions: Registry) -> Node:
    """Render the screen's one accented command.

    A floating action button is Material's shape for "create", and the icon
    inside it is the whole label. The id the binding carries is the command,
    not the control's position, so the host never learns which button this is.

    Args:
        theme: Colours to paint with.
        actions: The registry this screen binds its controls to.

    Returns:
        The FloatingActionButton declaration.
    """
    return FloatingActionButton(
        id="new",
        on_click=actions.new_note.bind(id="new"),
        container_color=theme.primary,
        children=[
            Icon(
                id="new_icon",
                image_vector=materialIcon(name="Filled.Add"),
                content_description="New note",
                tint=theme.background,
            )
        ],
    )


@composable
def previews_row(*, session: Session, theme: Theme, actions: Registry) -> Node:
    """Render the switch that decides whether rows show a line of body text.

    The switch owns its checked state on the native side and reports what it
    settled on; Python states the desired value in the snapshot. The label tells
    VoiceOver users what the switch is for, since a bare switch reads as nothing.

    Args:
        session: The session shell, which holds whether previews are shown.
        theme: Colours to paint with.
        actions: The registry this screen binds its controls to.

    Returns:
        A Row pairing the label with the Switch.
    """
    return Row(
        id="previews",
        vertical_alignment="center",
        children=[
            Text(
                id="previews_label",
                text="Show note previews",
                style="bodyMedium",
                color=theme.muted,
            ),
            Spacer(id="gap_previews_switch", modifier=Modifier().size(8)),
            Switch(
                id="previews_switch",
                checked=session.previews,
                on_checked_change=actions.set_previews.bind(id="previews"),
            ),
            Spacer(id="gap_previews_close", modifier=Modifier().size(8)),
        ],
    )


@composable
def listing_bar(*, session: Session, actions: Registry) -> Node:
    """Render the bar that filters the list.

    Each item names the filter it stands for in the binding, so one transition
    serves both items and the selected item is the session's choice read back.
    The icons sit in the item's own slot, so the host composes them where the
    bar puts them; the labels below them are the whole name of each filter.

    Args:
        session: The session shell, which holds the filter in force.
        actions: The registry this screen binds its controls to.

    Returns:
        The NavigationBar declaration.
    """
    return NavigationBar(
        id="listing_bar",
        children=[
            NavigationBarItem(
                id="listing_all",
                selected=session.listing == ALL_FILTER,
                on_click=actions.set_listing.bind(id="listing_all", value=ALL_FILTER),
                icon=[
                    Icon(
                        id="listing_all_icon",
                        image_vector=materialIcon(name="Filled.Home"),
                        content_description=None,
                    )
                ],
                label=[Text(id="listing_all_label", text="All notes")],
            ),
            NavigationBarItem(
                id="listing_text",
                selected=session.listing == TEXT_FILTER,
                on_click=actions.set_listing.bind(id="listing_text", value=TEXT_FILTER),
                icon=[
                    Icon(
                        id="listing_text_icon",
                        image_vector=materialIcon(name="Filled.Edit"),
                        content_description=None,
                    )
                ],
                label=[Text(id="listing_text_label", text="With text")],
            ),
        ],
    )


@composable
def about_sheet(
    *,
    session: Session,
    theme: Theme,
    actions: Registry,
    notes: list[Note],
) -> Node:
    """Render the sheet explaining what the app is and how it is built.

    Args:
        session: The session shell, which holds whether the sheet is open.
        theme: Colours to paint with.
        actions: The registry this screen binds its controls to.
        notes: The notes the bar inside the sheet measures.

    Returns:
        The ModalBottomSheet declaration.
    """
    return ModalBottomSheet(
        id="about_sheet",
        open=session.about_open,
        on_open_change=actions.set_about.bind(id="about_sheet"),
        children=[
            Column(
                id="about_body",
                modifier=Modifier().padding(20).fill_max_width(),
                children=[
                    Row(
                        id="about_heading",
                        vertical_alignment="center",
                        children=[
                            Icon(
                                id="about_icon",
                                image_vector=materialIcon(name="Filled.Info"),
                                content_description="About this app",
                                tint=theme.primary,
                            ),
                            Spacer(
                                id="gap_about_heading",
                                modifier=Modifier().size(8),
                            ),
                            Text(
                                id="about_title",
                                text="How this works",
                                style="titleMedium",
                                color=theme.on_surface,
                            ),
                        ],
                    ),
                    Spacer(id="gap_about_text", modifier=Modifier().size(8)),
                    Text(
                        id="about_text",
                        text=(
                            "Every control here is native Material 3. "
                            "Python states whether this sheet is open; "
                            "the host drives it and reports back what "
                            "it settled on."
                        ),
                        style="bodyMedium",
                        color=theme.muted,
                    ),
                    Spacer(id="gap_about_bar", modifier=Modifier().size(12)),
                    LinearProgressIndicator(
                        id="about_progress",
                        progress=filled_share(notes),
                    ),
                    Spacer(id="gap_about_note", modifier=Modifier().size(8)),
                    Text(
                        id="about_progress_note",
                        text=(
                            "That bar is Python state too: the share of "
                            "your notes that have a body. The value is "
                            "read during composition, so it tracks the "
                            "notes you keep."
                        ),
                        style="bodySmall",
                        color=theme.muted,
                    ),
                    Spacer(id="gap_about_close", modifier=Modifier().size(12)),
                    TextButton(
                        id="about_close",
                        text="Got it",
                        on_click=actions.set_about.bind(id="about_close", open=False),
                    ),
                ],
            ),
        ],
    )


@composable
def note_row(
    *,
    note: Note,
    previews: bool,
    theme: Theme,
    actions: Registry,
) -> Node:
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
        actions: The registry this screen binds its controls to.

    Returns:
        A clickable Card carrying this note's bindings.
    """
    caption: list[Node] = [
        Text(
            id="title",
            text=note.label,
            style="titleMedium",
            color=theme.on_surface,
        )
    ]
    if previews:
        caption.append(
            Text(
                id="preview",
                text=note.preview(),
                style="bodySmall",
                color=theme.muted,
            )
        )
    return Card(
        id="row",
        on_click=actions.open_note.bind(id=f"n{note.id}", note_id=note.id),
        modifier=Modifier().padding(PaddingValues(bottom=Dp(8))).fill_max_width(),
        children=[
            Row(
                id="row",
                vertical_alignment="center",
                modifier=Modifier().padding(10),
                children=[
                    Column(
                        id="text",
                        modifier=Modifier().fill_max_width(0.75),
                        children=caption,
                    ),
                    TextButton(
                        id="delete",
                        text="Delete",
                        on_click=actions.delete_note.bind(
                            id=f"n{note.id}", note_id=note.id
                        ),
                    ),
                ],
            )
        ],
    )
