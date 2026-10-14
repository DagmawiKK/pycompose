"""Notes — a two-screen MVVM app written entirely in Python.

The host calls :func:`build` once per process, hands back the route it restored
and the app state it saved, and expects a :class:`~pycompose.state.State` back.

Layout, bottom to top:

* ``notes_app/domain/`` -- what a note is and what you can do with notes. Plain
  functions, no imports from anything above.
* ``notes_app/data/`` -- how notes are actually kept, behind the domain's
  ``Protocol``.
* ``notes_app/container.py`` -- the app's long-lived objects, built once.
* ``notes_app/state.py`` -- ``Session``, the shell that survives process death.
* ``notes_app/theme.py`` -- the palette, chosen from a host-reported fact.
* ``notes_app/handlers.py`` -- the action references screens bind to.
* ``notes_app/views/`` -- composables, which describe UI and nothing else.
* ``notes_app/view_model.py`` -- shell plus repository become one snapshot.
* ``notes_app/actions.py`` -- the transitions a user can trigger.

There is no ``storage.py``. Encoding the state and decoding it back is derived
from the declarations, so the app never writes a codec and never learns that the
canonical JSON freeze turns arrays into tuples.

**Why the notes are not in the state.** ``restore`` travels through the host's
``SavedStateHandle``, which is a ``Bundle`` with a hard limit measured in
kilobytes. A thousand notes do not fit, and the exception that says so names
nothing useful. So only the shell — route, appearance — is published; the notes
live in a repository and are read when a screen needs them. Adding notes stops
costing more than adding a byte.

**How this differs from a Jetpack Compose app.** ``NavController`` swaps which
composable renders while the ViewModel survives untouched. Here a route change is
an ordinary inbound action, so this session is never rebuilt either — half-typed
text is still there after you navigate away and back. The route is *requested* by
a handler and *decided* by the host, which keeps one source of truth for what is
on screen.
"""

from __future__ import annotations

import json
from typing import cast

from notes_app.actions import actions
from notes_app.container import AppContainer
from notes_app.container import build as build_container
from notes_app.state import LIST_ROUTE, Session, seeded_session
from notes_app.view_model import held, snapshot

from pycompose.errors import StateError
from pycompose.state import State

__all__ = ["actions", "build", "container"]


def container() -> AppContainer:
    """Build the app's long-lived objects, once per process.

    The session looks for a module-level factory under exactly this name, calls
    it a single time, and hands the result to every ``build`` for the life of
    the process -- including after a hot reload, which is the point: reopening a
    file on every keystroke would become the app's dominant cost.

    Returns:
        The container this session will retain.
    """
    return build_container()


def build(
    *,
    route: str = LIST_ROUTE,
    restore: str = "",
    container: AppContainer | None = None,
) -> State:
    """Create the first snapshot for a freshly started process.

    Args:
        route: The route the host restored from its own saved state. This is the
            authority on which screen is showing, and it wins over the route
            recorded in ``restore``.
        restore: JSON this app published previously, handed straight back by the
            host. Empty on a first run.
        container: The app's long-lived objects. The session builds and installs
            one when this is None, which is the normal path; a test passes its
            own so nothing touches disk.

    Returns:
        The first snapshot for the requested route.
    """
    # Only a direct call without one, which the session never makes.
    supplied = container if container is not None else build_container()
    return snapshot(
        _rehydrated(restore).evolve(route=route), held(supplied.notes_repo), 0, actions
    )


def _rehydrated(restore: str) -> Session:
    """Return the shell the host's saved bytes describe.

    Args:
        restore: Canonical JSON from a previous snapshot, or empty on a first run.

    Returns:
        The restored shell, or a fresh one when the bytes are unusable. A corrupt
        save leaves a working app rather than a crash.
    """
    if not restore:
        return seeded_session()
    try:
        decoded = json.loads(restore)
        return cast("Session", Session.codec.decode(decoded))
    except (StateError, ValueError):
        # Siblings, not parent and child: the parse raises ValueError and the
        # codec raises StateError, and a save that is either unreadable or
        # unreadable-as-this-app is the same problem to the user.
        return seeded_session()
