"""The Notes application.

A two-screen app written entirely in Python. Nothing in this package imports
Android, Chaquopy or Compose; every control it declares is a native Material 3
component the Android host renders.

Layers, each importing only the ones below it in this list:

* :mod:`notes_app.views` -- screens, pure functions of their view model's state.
* :mod:`notes_app.view_models` -- each screen's state, intents and behaviour.
* :mod:`notes_app.routes` -- where the app can go.
* :mod:`notes_app.domain` -- what a note is and what you can do with notes.
"""
