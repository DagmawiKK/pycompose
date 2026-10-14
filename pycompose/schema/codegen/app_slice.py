"""Per-app codegen: emit only the components an app actually uses.

    python tools/schema/gen.py --app path/to/app

ADR-0014. The catalog says what exists; the app's source says what it uses; the
intersection is what gets built. Today the notes app uses nine of thirteen, and
the four it does not use are four Kotlin data classes and four Python
constructors it never touches. Mirroring Material 3 makes that 165 rather
than 4, which is the whole reason this exists.

Discovery is by name in the AST, not by grep and not by a manifest an app has to
remember to update. An app that stops referencing a component stops shipping it,
which is the property that makes the catalog safe to grow without anyone
maintaining a list.

The Python slice lives in the app's own ``m3`` package rather than being imported
from ``pycompose.m3``, and that is not a naming preference. If the app imported
the library's full catalog while its Kotlin carried only a subset, the app could
emit a node the host has no adapter for -- and it would fail as a blank screen at
runtime, not as an error at build time. Two slices generated from one filter
agree by construction; two independently maintained sets do not.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

APP_PACKAGE = "m3"
"""The app-side generated package, mirroring ``pycompose.m3``."""

_IR_RELATIVE = Path("android/ir/src/main/kotlin/com/pycompose/ir/generated")
_ADAPTERS_RELATIVE = Path(
    "android/host/src/main/kotlin/com/pycompose/host/ui/GeneratedAdapters.kt"
)


class AppCodegenError(Exception):
    """Raised when an app's component usage cannot be resolved."""


def discover(app: Path, catalog: dict[str, Any]) -> set[str]:
    """Return the component names an app references.

    Scans every ``.py`` under the app, skipping the generated package so the
    slice does not discover itself.

    Args:
        app: The app's root directory.
        catalog: Every component entry from ``components.json``.

    Returns:
        The referenced component names.

    Raises:
        AppCodegenError: If a name matches nothing in the catalog.
    """
    known = set(catalog["components"])
    used: set[str] = set()
    for source in sorted(app.rglob("*.py")):
        if APP_PACKAGE in source.relative_to(app).parts:
            continue
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            raise AppCodegenError(f"cannot parse {source}: {exc}") from exc
        for node in ast.walk(tree):
            # `from m3 import Button` binds an alias node, which is never an
            # ast.Name. Scanning names alone finds a component only where it is
            # *used*, so an app that imports one to re-export it -- or that
            # imports all nine and builds screens in another file -- would
            # silently drop them.
            if isinstance(node, ast.alias) and node.name in known:
                used.add(node.name)
            elif isinstance(node, ast.Name) and node.id in known:
                used.add(node.id)
            # `m3.Button` reads as an Attribute whose attr is the component.
            elif isinstance(node, ast.Attribute) and node.attr in known:
                used.add(node.attr)
    return used


def uses_generated_slice(python_root: Path, package: str = APP_PACKAGE) -> bool:
    """Report whether an app imports its own generated component package.

    This is what makes codegen bindable without a config flag. An app that
    imports ``pycompose.m3`` has adopted the library catalog and needs nothing
    generated; one that imports ``m3`` has adopted per-app codegen and needs it
    before every build. Detecting the import means an existing project cannot be
    broken by a build step that suddenly starts failing, and an adopter cannot
    silently keep a stale slice because nothing reminded it to regenerate.

    Args:
        python_root: Where the app's Python lives.
        package: The generated package's name.

    Returns:
        True when any module imports the generated package.
    """
    if not python_root.is_dir():
        return False
    for source in sorted(python_root.rglob("*.py")):
        if package in source.relative_to(python_root).parts:
            continue
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                alias.name == package for alias in node.names
            ):
                return True
            if isinstance(node, ast.ImportFrom) and (
                node.module == package or (node.module or "").startswith(f"{package}.")
            ):
                return True
    return False


def slice_registry(registry: dict[str, Any], used: set[str]) -> dict[str, Any]:
    """Return the catalog narrowed to the components an app uses.

    Everything except ``components`` is carried whole: actions, effects,
    lifecycle and modifiers are small, and a host that has heard of
    ``onRouteChanged`` but not ``Card`` is not a useful host.

    Args:
        registry: The parsed catalog.
        used: The component names the app references.

    Returns:
        A registry carrying only those components.
    """
    narrowed = {key: value for key, value in registry.items() if key != "components"}
    narrowed["components"] = {
        name: entry for name, entry in registry["components"].items() if name in used
    }
    return narrowed


def load_catalog(path: Path) -> dict[str, Any]:
    """Read ``components.json``.

    Args:
        path: The schema file.

    Returns:
        The parsed catalog.

    Raises:
        AppCodegenError: If the file is not valid JSON.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except json.JSONDecodeError as exc:
        raise AppCodegenError(f"invalid JSON in {path}: {exc}") from exc
