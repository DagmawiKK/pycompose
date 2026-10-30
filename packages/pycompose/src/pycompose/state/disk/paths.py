"""Host-provided private path facts, with no Android objects or discovery."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

__all__ = ["AppPaths", "install", "paths"]


@dataclass(frozen=True)
class AppPaths:
    """Private paths supplied as data before the app container is constructed.

    Attributes:
        files: Persistent app-private directory; not automatically encrypted.
        cache: Evictable app-private directory; never the only copy of durable data.
    """

    files: Path
    cache: Path


_installed: AppPaths | None = None


def install(files: str = "", cache: str = "") -> None:
    """Install path facts from the worker's host initialization.

    Args:
        files: Host's private persistent directory, or empty for desktop defaults.
        cache: Host's evictable directory, or empty for desktop defaults.
    """
    global _installed  # noqa: PLW0603 -- immutable facts, installed before app import
    _installed = AppPaths(Path(files), Path(cache)) if files and cache else None


def paths() -> AppPaths:
    """Read private paths without importing Android or obtaining native objects.

    Returns:
        Host facts, or PYCOMPOSE_HOME/current-directory desktop defaults.
    """
    root = Path(os.environ.get("PYCOMPOSE_HOME", Path.cwd()))
    return _installed or AppPaths(root, root / "cache")
