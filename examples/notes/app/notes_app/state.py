"""The app's state, declared rather than hand-encoded.

``AppState`` is what a Kotlin app gets from ``@Serializable``: the codec is
derived from the declaration, so there is no ``encode`` to write and no ``decode``
to keep in step with it.

Nothing here is the notes. Those live in a repository, on disk, because they
outgrow a Bundle; what remains is the session shell -- the small state every
screen needs, and the only part the host must be able to restore.
"""

from __future__ import annotations

from pycompose.state import AppState

LIST_ROUTE = "notes"
DETAIL_PREFIX = "note:"

TEXT_FILTER = "with_text"
"""The listing that keeps only the notes carrying a body."""

ALL_FILTER = "all"
"""The listing that keeps every note."""


def detail_route(note_id: int) -> str:
    """Return the route naming one note.

    Args:
        note_id: Identity the route should address.

    Returns:
        The detail route.
    """
    return f"{DETAIL_PREFIX}{note_id}"


def note_in(route: str) -> int | None:
    """Return the note id a route addresses.

    Args:
        route: The route being shown.

    Returns:
        The note id, or None when the route is the list or is not a note route.
    """
    if not route.startswith(DETAIL_PREFIX):
        return None
    raw = route.removeprefix(DETAIL_PREFIX)
    return int(raw) if raw.isdigit() else None


class Session(AppState):
    """The session shell: the small state every screen needs.

    Kept apart from the notes on purpose. This is the part small enough to hand
    to the host on every snapshot and to restore after process death, and it is
    the only part the host has to keep while fifteen screens come and go.

    Attributes:
        route: Which screen is showing.
        dark: Whether the device is in dark mode.
        title_caret: Where the caret sits in the title field.
        body_caret: Where the caret sits in the body field.
        about_open: Whether the about sheet is showing.
        previews: Whether rows show a line of the note's body.
        listing: Which filter the list is showing.
    """

    route: str = LIST_ROUTE
    dark: bool = False
    title_caret: int = 0
    body_caret: int = 0
    about_open: bool = False
    previews: bool = True
    listing: str = ALL_FILTER


def seeded_session() -> Session:
    """Return the shell a genuinely fresh install starts from.

    Returns:
        A session on the list, in light mode.
    """
    return Session()
