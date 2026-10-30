"""pycompose.state — the app's own data, typed."""

from __future__ import annotations

from typing import Any

from pycompose.state.app_state import AppState
from pycompose.state.app_state_types import Loaded

__all__ = ["AppState", "Loaded"]

_VIEW_MODEL = "define an Intent and handle it in a ViewModel (pycompose.app)"
REMOVED = {
    "App": "use pycompose.app.App, built from destinations and view models",
    "Actions": _VIEW_MODEL,
    "ActionHandler": _VIEW_MODEL,
    "Registry": _VIEW_MODEL,
    "ShellResponse": "emit effects from a ViewModel with emit()",
    "respond": "emit effects from a ViewModel with emit()",
    "actions_for_module": _VIEW_MODEL,
}
"""Names this package no longer has, and what replaced each."""


def __getattr__(name: str) -> Any:
    if name in REMOVED:
        raise ImportError(f"pycompose.state.{name} was removed: {REMOVED[name]}")
    raise AttributeError(f"module 'pycompose.state' has no attribute {name!r}")
