"""Composables. They describe UI and nothing else.

Every function here takes its model, its theme and its handlers as arguments and
returns a node declaration. No view reads global state, performs IO, or decides
what a tap means.
"""

from notes_app.views.editor_screen import editor_screen
from notes_app.views.list_screen import list_screen

__all__ = ["editor_screen", "list_screen"]
