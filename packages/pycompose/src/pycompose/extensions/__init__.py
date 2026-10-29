"""Moved to :mod:`pycompose.storage.paths`; this name works for one release.

``pycompose.extensions`` is kept free for the library adapters of ADR-0063,
which are distributions of their own (``pycompose_sqlite`` and the like).
"""

from __future__ import annotations

from typing import Any

from pycompose._moved import forward

forward(
    __name__,
    "pycompose.storage.paths",
    globals(),
    submodules={"environment": "pycompose.storage.paths"},
)

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
