"""setuptools, after assembling the package's copied assets.

The wheel carries copies of files that live once elsewhere in the repository
(``tools/template/sync.py``). In a checkout they are assembled before every
build; an sdist already holds them, and has no ``android/`` to assemble from.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from setuptools import build_meta as _setuptools
from setuptools.build_meta import *  # noqa: F403 -- the PEP 517 hooks

# packages/pycompose/_build/backend.py: the checkout is three folders up.
ROOT = Path(__file__).resolve().parents[3]


def _assemble() -> None:
    if not (ROOT / "android").is_dir():
        return
    spec = importlib.util.spec_from_file_location(
        "sync", ROOT / "tools/template/sync.py"
    )
    assert spec is not None and spec.loader is not None
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    sync.assemble()


def build_wheel(wheel_directory: str, *args: Any, **kwargs: Any) -> str:
    """Assemble, then build the wheel."""
    _assemble()
    return _setuptools.build_wheel(wheel_directory, *args, **kwargs)


def build_sdist(sdist_directory: str, *args: Any, **kwargs: Any) -> str:
    """Assemble, then build the sdist, which then carries the copies."""
    _assemble()
    return _setuptools.build_sdist(sdist_directory, *args, **kwargs)


def build_editable(wheel_directory: str, *args: Any, **kwargs: Any) -> str:
    """Assemble, then install in place."""
    _assemble()
    return _setuptools.build_editable(wheel_directory, *args, **kwargs)
