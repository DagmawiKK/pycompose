"""Smoke tests: the package imports cleanly and reports a version."""

from __future__ import annotations

import pycompose
from pycompose import __version__
from pycompose.errors import PyComposeError


def test_version_is_string() -> None:
    assert isinstance(__version__, str)
    assert __version__


def test_public_init_exports_version_and_composition() -> None:
    assert pycompose.__all__ == [
        "AppContext",
        "Registry",
        "__version__",
        "action",
        "async_task",
        "composable",
        "context",
        "install_context",
        "repository",
    ]
    assert callable(pycompose.composable)
    assert callable(pycompose.action)


def test_error_hierarchy_base() -> None:
    assert issubclass(PyComposeError, Exception)
