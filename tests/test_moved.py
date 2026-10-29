"""Moved modules: the old name warns once and hands over the same objects."""

from __future__ import annotations

import importlib
import sys

import pytest

MOVED = [
    ("pycompose.repository", "pycompose.storage.documents", "Document"),
    ("pycompose.media", "pycompose.storage.media", "image"),
    ("pycompose.extensions", "pycompose.storage.paths", "paths"),
    ("pycompose.extensions.environment", "pycompose.storage.paths", "paths"),
]


@pytest.mark.parametrize(("old", "new", "name"), MOVED)
def test_an_old_name_warns_and_is_the_same_object(
    old: str, new: str, name: str
) -> None:
    # Forget the old top-level module and its children, so the shim runs again.
    top = ".".join(old.split(".")[:2])
    for module in [m for m in sys.modules if m == top or m.startswith(f"{top}.")]:
        del sys.modules[module]
    with pytest.warns(DeprecationWarning, match=new):
        moved = importlib.import_module(old)
    assert getattr(moved, name) is getattr(importlib.import_module(new), name)


def test_a_name_removed_in_the_cleanup_still_says_what_replaced_it() -> None:
    with pytest.warns(DeprecationWarning):
        extensions = importlib.reload(importlib.import_module("pycompose.extensions"))
    with pytest.raises(ImportError, match="to_thread"):
        extensions.Resource  # noqa: B018
