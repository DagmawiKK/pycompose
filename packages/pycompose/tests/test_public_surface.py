"""The public surface: every name an app may import, reviewed here.

A public package's ``__init__`` is its API. Adding or removing a name changes
what apps can rely on, so it changes this file too; ``host`` and ``model`` are
internal whole, and no example or template reaches into them.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

from pycompose.ui._generated import components, values

ROOT = Path(__file__).resolve().parents[3]

SURFACE = {
    "pycompose": ["Expression", "Stream", "__version__", "composable"],
    "pycompose.app": [
        "App",
        "Destination",
        "Failure",
        "Finish",
        "Haptic",
        "Home",
        "Intent",
        "Navigate",
        "OpenUrl",
        "PickFile",
        "Pop",
        "Push",
        "Replace",
        "Route",
        "Span",
        "StateFlow",
        "Toast",
        "TypedEffect",
        "ViewModel",
        "to_thread",
    ],
    "pycompose.app.blocks": [
        "Accordion",
        "Blocks",
        "Button",
        "ChatInterface",
        "Chatbot",
        "Checkbox",
        "Column",
        "Component",
        "Dropdown",
        "Event",
        "File",
        "Gallery",
        "Image",
        "Interface",
        "JSON",
        "Label",
        "Markdown",
        "Number",
        "Radio",
        "Row",
        "Slider",
        "Tab",
        "Tabs",
        "Textbox",
        "UploadButton",
    ],
    "pycompose.state": [
        "AppState",
        "Document",
        "Loaded",
        "Repository",
        "documents_root",
        "image",
        "paths",
    ],
}
"""Each public package's names, as its ``__all__`` states them."""

UI_OWN = ["Fallback", "Intent", "Modifier", "Node"]
"""What ``pycompose.ui`` adds by hand to the catalog's components and values."""

APPS = (
    "examples",
    "android/host/src/main/python",
    "packages/pycompose-cli/src/pycompose_cli/templates/overlay",
)
"""Where the code an app writes lives: examples, the host sample, the template."""

BUILT = {".pycompose", "build", "components", "__pycache__", "tests"}
"""Folders under those that are build output, a generated slice or tests."""


@pytest.mark.parametrize("package", sorted(SURFACE))
def test_a_public_package_exports_exactly_its_reviewed_names(package: str) -> None:
    module = importlib.import_module(package)
    assert sorted(module.__all__) == SURFACE[package]


def test_ui_exports_every_component_and_value_and_its_own_names() -> None:
    ui = importlib.import_module("pycompose.ui")
    generated = {*components.__all__, *values.__all__}
    assert generated.isdisjoint(UI_OWN)
    for name in sorted({*generated, *UI_OWN}):
        assert hasattr(ui, name), name


def _app_sources() -> list[Path]:
    return [
        path
        for folder in APPS
        for path in (ROOT / folder).rglob("*.py")
        if not BUILT.intersection(path.relative_to(ROOT / folder).parts)
    ]


def test_apps_import_only_public_packages() -> None:
    public = {*SURFACE, "pycompose.ui"}
    reached = {}
    for path in _app_sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            for name in names:
                if name.startswith("pycompose.") and name not in public:
                    reached[str(path.relative_to(ROOT))] = name
    assert _app_sources()
    assert reached == {}
