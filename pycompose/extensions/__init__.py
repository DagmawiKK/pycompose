"""Where the app's private files live on the device."""

from __future__ import annotations

from typing import Any

from pycompose.extensions.environment import AppPaths, paths

__all__ = ["AppPaths", "paths"]

REMOVED = {
    "Resource": "own the library object in the app's container and call it "
    "with pycompose.app.to_thread",
    "Task": "use ViewModel.launch, which returns a task you can cancel",
}
"""Names this package no longer has, and what replaced each."""


def __getattr__(name: str) -> Any:
    if name in REMOVED:
        raise ImportError(f"pycompose.extensions.{name} was removed: {REMOVED[name]}")
    raise AttributeError(f"module 'pycompose.extensions' has no attribute {name!r}")
