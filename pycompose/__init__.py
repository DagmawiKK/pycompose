"""PyCompose: a Python UI library for Android (Jetpack Compose Material 3).

Names load on first use, so importing a submodule never imports the rest. An
app's own types come from :mod:`pycompose.app`.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from pycompose.version import __version__

if TYPE_CHECKING:
    from pycompose import repository
    from pycompose.composition import composable
    from pycompose.core.expressions import Expression, Stream

__all__ = ["Expression", "Stream", "__version__", "composable", "repository"]

_LAZY = {
    "Expression": ("pycompose.core.expressions", "Expression"),
    "Stream": ("pycompose.core.expressions", "Stream"),
    "composable": ("pycompose.composition", "composable"),
    "repository": ("pycompose.repository", None),
}

REMOVED = {
    "action": "define an Intent and handle it in a ViewModel (pycompose.app)",
    "Registry": "define an Intent and handle it in a ViewModel (pycompose.app)",
    "async_task": "use ViewModel.launch with pycompose.app.to_thread",
    "AppContext": "hand dependencies to a view model from the app's container",
    "context": "hand dependencies to a view model from the app's container",
    "install_context": "hand dependencies to a view model from the app's container",
}
"""Names this package no longer has, and what replaced each."""


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        module, attribute = _LAZY[name]
        loaded = importlib.import_module(module)
        value = loaded if attribute is None else getattr(loaded, attribute)
        globals()[name] = value
        return value
    if name in REMOVED:
        raise ImportError(f"pycompose.{name} was removed: {REMOVED[name]}")
    raise AttributeError(f"module 'pycompose' has no attribute {name!r}")
