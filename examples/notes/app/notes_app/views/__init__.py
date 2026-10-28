"""Composables. They describe UI and nothing else.

Every function here takes its state as an argument and returns a
node declaration. No view reads global state, performs IO, or decides what a tap
means. Colours are roles of the app's Material theme (``[theme]`` in
``pycompose.toml``), so dark mode is the theme's job, not the view's.
"""

from notes_app.views.editor_screen import editor_screen
from notes_app.views.list_screen import list_screen

__all__ = ["editor_screen", "list_screen"]
