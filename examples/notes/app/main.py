"""Notes — a two-screen MVVM app written entirely in Python.

The session finds :data:`app` in this module and runs it: the entry object
owns the shell seed, the view, and the container factory, and it performs the
restore dance — the host's bytes are decoded through the shell's own codec,
and a save that is unreadable or unreadable-as-this-app falls back to the
seed, so a corrupt save leaves a working app rather than a crash.

Layout, bottom to top:

* ``notes_app/domain/`` -- what a note is and what you can do with notes. Plain
  functions, no imports from anything above.
* ``notes_app/data/`` -- how notes are actually kept, behind the domain's
  ``Protocol``.
* ``notes_app/container.py`` -- the app's long-lived objects, built once.
* ``notes_app/state.py`` -- ``Session``, the shell that survives process death.
* ``notes_app/handlers.py`` -- the action references screens bind to.
* ``notes_app/views/`` -- composables, which describe UI and nothing else.
* ``notes_app/view_model.py`` -- shell plus repository become one screen.
* ``notes_app/actions.py`` -- the transitions a user can trigger. Each is
  session-native: its first parameter is the shell, and returning the shell
  (or ``respond(shell, *effects)``) is the whole of the transition.

There is no ``storage.py``. Encoding the state and decoding it back is derived
from the declarations, so the app never writes a codec and never learns that
the canonical JSON freeze turns arrays into tuples.

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

from notes_app.actions import actions
from notes_app.container import build as build_container
from notes_app.state import Session, seeded_session
from notes_app.view_model import screen

from pycompose import context
from pycompose.core.node import Node
from pycompose.state import App

__all__ = ["actions", "app"]


def view(session: Session) -> Node:
    """Compose the screen this shell is showing.

    The notes are read from the repository the context carries, which the
    session installed before this runs — the same way a handler reaches a
    use case, by name, from the ambient.

    Args:
        session: The shell after rehydration, with the host's route applied.

    Returns:
        The screen for this shell.
    """
    return screen(session, context().notes.list())


app = App(
    state=seeded_session,
    view=view,
    container=build_container,
    route="route",
)
