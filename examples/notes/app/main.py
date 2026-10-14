"""Notes — a two-screen MVVM app written entirely in Python.

The host calls :func:`build` once per process, hands back the route it restored
and the app state it saved, and expects a :class:`~pycompose.state.State` back.

Layout, bottom to top:

* ``notes_app/state.py`` -- ``Session`` (the shell) and ``NotesState`` (a feature
  partition), both declared with ``AppState``.
* ``notes_app/theme.py`` -- the palette, chosen from a host-reported fact.
* ``notes_app/handlers.py`` -- the action references screens bind to.
* ``notes_app/views/`` -- composables, which describe UI and nothing else.
* ``notes_app/view_model.py`` -- declared state becomes one snapshot.
* ``notes_app/actions.py`` -- the transitions a user can trigger.

There is no ``storage.py``. Encoding the state and decoding it back is derived
from the declarations, so the app never writes a codec and never learns that the
canonical JSON freeze turns arrays into tuples.

**How this differs from a Jetpack Compose app.** ``NavController`` swaps which
composable renders while the ViewModel survives untouched. Here a route change is
an ordinary inbound action, so this session is never rebuilt either — half-typed
text is still there after you navigate away and back. The route is *requested* by
a handler and *decided* by the host, which keeps one source of truth for what is
on screen.
"""

from __future__ import annotations

import json

from notes_app.actions import HANDLERS, actions
from notes_app.state import LIST_ROUTE, NotesState, Session
from notes_app.view_model import decode, snapshot

from pycompose.state import State

__all__ = ["actions", "build"]


def build(*, route: str = LIST_ROUTE, restore: str = "") -> State:
    """Create the first snapshot for a freshly started process.

    Args:
        route: The route the host restored from its own saved state. This is the
            authority on which screen is showing, and it wins over the route
            recorded in ``restore``.
        restore: JSON this app published previously, handed straight back by the
            host. Empty on a first run.

    Returns:
        The first snapshot for the requested route.
    """
    session, notes = _rehydrated(restore)
    return snapshot(session.evolve(route=route), notes, 0, HANDLERS)


def _rehydrated(restore: str) -> tuple[Session, NotesState]:
    """Return the declared state the host's saved bytes describe.

    Args:
        restore: Canonical JSON from a previous snapshot, or empty on a first run.

    Returns:
        The restored shell and notes partition, or fresh ones when the bytes are
        unusable. A corrupt save leaves a working app rather than a crash.
    """
    if not restore:
        return decode(None)
    try:
        return decode(json.loads(restore))
    except ValueError:
        return decode(None)
