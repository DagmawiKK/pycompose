"""Import an app from its source directory as it is on disk, and leave no trace."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def fresh_imports(source: Path) -> Iterator[None]:
    """Make ``source`` importable, with no stale module standing in for the app's.

    A module of the same name already imported -- an earlier session's, or any
    other ``main`` -- would otherwise be found before the app's own. Whatever
    the app imports is dropped afterwards, and what was set aside comes back.

    Args:
        source: The app's Python source directory.

    Yields:
        None: While the app is importable.
    """
    names = {
        path.stem for path in source.iterdir() if path.suffix == ".py" or path.is_dir()
    }
    hidden = {
        name: module
        for name, module in sys.modules.items()
        if name.split(".")[0] in names
    }
    for name in hidden:
        del sys.modules[name]
    before = set(sys.modules)
    sys.path.insert(0, str(source))
    try:
        yield
    finally:
        sys.path.remove(str(source))
        for name in set(sys.modules) - before:
            del sys.modules[name]
        sys.modules.update(hidden)
