"""pycompose.state — the app's own data, in memory and on disk.

``AppState`` declares what a view model holds and how it is saved; on disk, a
``Repository`` keeps ``Document``s atomically, ``paths`` names the app's
folders and ``image`` saves what the app shows from files.
"""

from __future__ import annotations

from typing import Any

from pycompose.state.disk.documents import Document, Repository
from pycompose.state.disk.media import image
from pycompose.state.disk.paths import paths
from pycompose.state.memory.app_state import AppState
from pycompose.state.memory.types import Loaded

__all__ = ["AppState", "Document", "Loaded", "Repository", "image", "paths"]

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
