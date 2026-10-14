"""The action references a screen binds its controls to.

This module exists to keep the dependency arrows pointing one way. A screen needs
an action object in order to bind it, and an action needs the view-model in order
to build the next snapshot; if views imported actions directly the three modules
would form a cycle. Passing the references in as data breaks it, and it has the
pleasant side effect of making every view a plain function of its inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pycompose.state.app_action import AppAction


@dataclass(frozen=True, slots=True)
class Handlers:
    """Every action a screen may bind to.

    Attributes:
        new_note: Create a note and open it.
        open_note: Open an existing note by its bound id.
        set_title: Record the title field's text.
        set_body: Record the body field's text.
        delete_note: Remove the note carrying the bound id.
        go_back: Return to the list from the editor.
        show_about: Explain where the UI comes from.
    """

    new_note: AppAction[Any, Any]
    open_note: AppAction[Any, Any]
    set_title: AppAction[Any, Any]
    set_body: AppAction[Any, Any]
    delete_note: AppAction[Any, Any]
    go_back: AppAction[Any, Any]
    show_about: AppAction[Any, Any]
