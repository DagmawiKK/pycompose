"""Where a checkout of this repository keeps what the tools read and write.

The catalog tools read ``schema/`` and write into ``android/`` and into the
package's own source, which only a checkout has. They find it by its markers
rather than by counting folders up from a file, so moving a module or the
package does not move what they read.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["PACKAGE", "ROOT"]

PACKAGE = Path(__file__).resolve().parents[1]
"""The ``pycompose`` package's own folder."""


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
