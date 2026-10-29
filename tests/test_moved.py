"""Moved modules: the old name warns once and hands over the same objects."""

from __future__ import annotations

import importlib
import re
import sys

import pytest

# Old name, the module it became, a name in it, and the move the warning names:
# a submodule's old name runs its package's shim, which names the package.
MOVED = [
    (
        "pycompose.repository",
        "pycompose.storage.documents",
        "Document",
        "pycompose.storage.documents",
    ),
    ("pycompose.media", "pycompose.storage.media", "image", "pycompose.storage.media"),
    (
        "pycompose.extensions",
        "pycompose.storage.paths",
        "paths",
        "pycompose.storage.paths",
    ),
    (
        "pycompose.extensions.environment",
        "pycompose.storage.paths",
        "paths",
        "pycompose.storage.paths",
    ),
    ("pycompose.ir", "pycompose.wire", "emit_ir", "pycompose.wire"),
    ("pycompose.ir.model", "pycompose.wire.model", "IRRoot", "pycompose.wire"),
    ("pycompose.components", "pycompose.ui", "Modifier", "pycompose.ui"),
    ("pycompose.components.layout", "pycompose.ui.layout", "Column", "pycompose.ui"),
    # Split in two: each half's names are the same objects through the old one.
    ("pycompose.m3", "pycompose.foundation", "Column", "pycompose.foundation and"),
    ("pycompose.m3", "pycompose.material3", "Button", "pycompose.foundation and"),
    (
        "pycompose.composition",
        "pycompose.ui.composition",
        "composable",
        "pycompose.ui.composition",
    ),
]


@pytest.mark.parametrize(("old", "new", "name", "warned"), MOVED)
def test_an_old_name_warns_and_is_the_same_object(
    old: str, new: str, name: str, warned: str
) -> None:
    # Forget the old top-level module and its children, so the shim runs again.
    top = ".".join(old.split(".")[:2])
    for module in [m for m in sys.modules if m == top or m.startswith(f"{top}.")]:
        del sys.modules[module]
    with pytest.warns(DeprecationWarning, match=f"moved to {re.escape(warned)}"):
        moved = importlib.import_module(old)
    assert getattr(moved, name) is getattr(importlib.import_module(new), name)


def test_a_name_removed_in_the_cleanup_still_says_what_replaced_it() -> None:
    with pytest.warns(DeprecationWarning):
        extensions = importlib.reload(importlib.import_module("pycompose.extensions"))
    with pytest.raises(ImportError, match="to_thread"):
        extensions.Resource  # noqa: B018
