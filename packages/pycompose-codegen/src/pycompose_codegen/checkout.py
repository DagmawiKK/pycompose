"""Where a checkout of this repository keeps what the tools read and write.

The catalog tools read ``schema/`` and write into ``android/`` and into the
package's own source, which only a checkout has. They find it by its markers
rather than by counting folders up from a file, so moving a module or the
package does not move what they read.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

__all__ = ["PACKAGE", "ROOT"]


def _runtime() -> Path:
    spec = importlib.util.find_spec("pycompose")
    assert spec is not None and spec.origin is not None, "pycompose is not installed"
    return Path(spec.origin).resolve().parent


PACKAGE = _runtime()
"""The runtime package's own folder: its source in a checkout, else where it is
installed. Found without importing it, so the tools stay off its import graph."""


def _root() -> Path:
    holder = PACKAGE.parent
    for folder in (holder, *holder.parents):
        if (folder / "android" / "settings.gradle.kts").is_file():
            return folder
    # Installed from a wheel: no checkout above, so the folder holding the
    # package, where the checkout-only files are simply absent.
    return holder


ROOT = _root()
"""The checkout: the folder holding ``android/`` and ``schema/``."""
