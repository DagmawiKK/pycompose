"""The Notes application.

A two-screen MVVM app written entirely in Python. Nothing in this package
imports Android, Chaquopy or Compose; every control it declares is a native
Material 3 component the Android host renders.

Layers, each importing only the ones above it in this list:

* :mod:`notes_app.state` -- the app's data, declared with ``AppState``.
* :mod:`notes_app.handlers` -- the controls' action references.
* :mod:`notes_app.views` -- composables, describing UI and nothing else.
* :mod:`notes_app.view_model` -- declared state becomes one snapshot.
* :mod:`notes_app.actions` -- the transitions a user can trigger.
"""

from notes_app.actions import actions

__all__ = ["actions", "actions"]
