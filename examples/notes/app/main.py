"""Notes -- a two-screen app written entirely in Python.

The session finds :data:`app` in this module and runs it. Each route opens a
destination: a view model built from the container, and a screen that draws
the view model's state. The session keeps the back stack, and saves every
entry's state so process death restores the whole stack.

Layout, bottom to top:

* ``notes_app/domain/`` -- what a note is and what you can do with notes. Plain
  functions, no imports from anything above.
* ``notes_app/data/`` -- how notes are actually kept, behind the domain's
  ``Protocol``.
* ``notes_app/container.py`` -- the app's long-lived objects, built once.
* ``notes_app/routes.py`` -- where the app can go.
* ``notes_app/view_models/`` -- each screen's state, intents and behaviour.
* ``notes_app/views/`` -- screens, pure functions of their state.

**Why the notes are not saved.** Saved state travels through the host's
``SavedStateHandle``, a ``Bundle`` with a hard limit measured in kilobytes. A
thousand notes do not fit. So the notes are ``Loaded`` fields: read from the
repository when a view model is built and never saved. What is saved is small:
the carets, the filter, whether the sheet is open.
"""

from __future__ import annotations

from notes_app.container import AppContainer, build
from notes_app.routes import EditorRoute, NotesRoute
from notes_app.view_models import EditorViewModel, ListViewModel
from notes_app.views import editor_screen, list_screen

from pycompose.app import App, Destination

__all__ = ["app"]


def _list(container: AppContainer, _route: NotesRoute) -> ListViewModel:
    return ListViewModel(container.notes, container.listing)


def _editor(container: AppContainer, route: EditorRoute) -> EditorViewModel:
    return EditorViewModel(container.notes, route.note_id)


app = App(
    start=NotesRoute(),
    destinations={
        NotesRoute: Destination(_list, list_screen),
        EditorRoute: Destination(_editor, editor_screen),
    },
    container=build,
    deep_links=frozenset({EditorRoute}),
)
"""The Notes application."""
