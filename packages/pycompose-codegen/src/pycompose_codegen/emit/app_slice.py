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
from ``pycompose.foundation`` and ``pycompose.material3``, and that is not a
naming preference. If the app imported
the library's full catalog while its Kotlin carried only a subset, the app could
emit a node the host has no adapter for -- and it would fail as a blank screen at
runtime, not as an error at build time. Two slices generated from one filter
agree by construction; two independently maintained sets do not.
"""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
from typing import Any

from pycompose.model.catalog.registry_rules import with_rules

APP_PACKAGE = "m3"
"""The app-side generated package: the library's two component packages in one."""

LAYERS = ("pycompose.blocks",)
"""Library packages that draw native components for an app: an app importing one
carries the components the package draws, found in its source as an app's are."""

APP_LOCK = "compose.lock.json"
"""The app's lock slice beside ``pycompose.toml``: its own libraries' components,
compiled by ``pycompose add`` and committed like a lock file."""

GENERATED_RELATIVE = Path(".pycompose/generated")
"""Where a project's generated slice lives, relative to the project root.

The scaffold's modules bind this tree through their build files, so it is build
output rather than a module source: the CLI regenerates it before every build
(ADR-0014), the template's ``.gitignore`` ignores it, and no second copy lives
under ``android/``. The notes example generates into it too, and commits the
result as the slice fixture.

The layout mirrors the module trees the files used to sit in -- ``ir/``,
``renderer/`` and ``host/`` -- so one ``srcDir`` per module binds exactly the
files that module compiles.
"""

_IR_RELATIVE = GENERATED_RELATIVE / "ir/src/main/kotlin/com/pycompose/ir/generated"
_VALUES_RELATIVE = (
    GENERATED_RELATIVE
    / "renderer/src/main/kotlin/com/pycompose/renderer/generated/ValueResolver.kt"
)
_ADAPTERS_RELATIVE = (
    GENERATED_RELATIVE
    / "host/src/main/kotlin/com/pycompose/host/ui/GeneratedAdapters.kt"
)

FLOOR_COMPONENTS = frozenset(
    {
        "Image",
        "PlainTooltip",
        "RichTooltip",
        "SearchBarInputField",
        "StatefulSearchBarInputField",
        "StatefulSearchBar",
        "SearchBarStateInputField",
        "ExpandedDockedSearchBar",
        "ExpandedFullScreenSearchBar",
        "Text",
        "TextField",
        "TooltipBox",
    }
)
"""Components every generated host compiles against, referenced or not.

``host/.../ui/BuiltinComponents.kt`` is hand-written and always compiled: it
registers the components whose behavior is not mechanical and names their
generated node classes by type, so a slice without them would emit a host that
does not compile. Keeping them in every slice is what lets
those adapters stay hand-written once instead of being re-derived per app; the
generated adapters file skips them for the same reason. Every other component
enters a slice only because the app references it, and
``tests/test_app_codegen.py`` scans the hand-written Kotlin so a new reference
without a floor entry fails there rather than in a user's build.
"""


class AppCodegenError(Exception):
    """Raised when an app's component usage cannot be resolved."""


def discover(app: Path, catalog: dict[str, Any]) -> set[str]:
    """Return the component names an app references.

    Scans every ``.py`` under the app, skipping the generated package so the
    slice does not discover itself.

    Unreadable Python syntax propagates AppCodegenError.

    Args:
        app: The app's root directory.
        catalog: Every component entry from the catalog lock.

    Returns:
        The referenced component names.

    """
    return _discover_names(app, set(catalog["components"]))


def discover_values(app: Path, catalog: dict[str, Any]) -> set[str]:
    """Return explicitly referenced approved value constructors, excluding output."""
    from pycompose_codegen.emit.values import definitions

    return _discover_names(app, set(definitions(catalog)))


def _discover_names(app: Path, known: set[str]) -> set[str]:
    used: set[str] = set()
    for source in _sources(app):
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


def _app_sources(python_root: Path, package: str = APP_PACKAGE) -> list[Path]:
    """The app's own modules, without its generated package."""
    return [
        source
        for source in sorted(python_root.rglob("*.py"))
        if package not in source.relative_to(python_root).parts
    ]


def _sources(app: Path) -> list[Path]:
    """The app's modules, and those of every drawing layer it imports."""
    found = _app_sources(app)
    for layer in layers_used(app):
        spec = importlib.util.find_spec(layer)
        if spec is not None and spec.origin is not None:
            found.extend(sorted(Path(spec.origin).parent.rglob("*.py")))
    return found


def _imported(python_root: Path, package: str = APP_PACKAGE) -> set[str]:
    """Every module the app's own sources import, by full name."""
    modules: set[str] = set()
    if not python_root.is_dir():
        return modules
    for source in _app_sources(python_root, package):
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
                modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def layers_used(python_root: Path) -> list[str]:
    """Return the drawing layers an app imports.

    Args:
        python_root: Where the app's Python lives.

    Returns:
        The names in :data:`LAYERS` it imports, in that order.
    """
    imported = _imported(python_root)
    return [
        layer
        for layer in LAYERS
        if any(name == layer or name.startswith(f"{layer}.") for name in imported)
    ]


def needs_slice(python_root: Path) -> bool:
    """Report whether a build must generate an app's component slice.

    Args:
        python_root: Where the app's Python lives.

    Returns:
        True for an app on its own generated package or on a drawing layer.
    """
    return uses_generated_slice(python_root) or bool(layers_used(python_root))


def uses_generated_slice(python_root: Path, package: str = APP_PACKAGE) -> bool:
    """Report whether an app imports its own generated component package.

    This is what makes codegen bindable without a config flag. An app that
    imports ``pycompose.material3`` has adopted the library catalog and needs nothing
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
    return any(
        name == package or name.startswith(f"{package}.")
        for name in _imported(python_root, package)
    )


def slice_registry(
    registry: dict[str, Any], used: set[str], *, values: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """Return the catalog narrowed to the components an app uses.

    Everything except ``components`` is carried whole: actions, effects,
    lifecycle and modifiers are small, and a host that has heard of
    ``onRouteChanged`` but not ``Card`` is not a useful host.

    Args:
        registry: The parsed catalog.
        used: The component names the app references.
        values: Explicitly referenced value constructors.

    Returns:
        A registry carrying only those components.
    """
    components = registry["components"]
    # A primary's overloads come with it: the keywords of a call, not its
    # name, decide which of them reaches the wire.
    reached = used | {
        name for name, entry in components.items() if entry.get("overloadOf") in used
    }
    narrowed = {key: value for key, value in registry.items() if key != "components"}
    narrowed["components"] = {
        name: entry for name, entry in components.items() if name in reached
    }
    from pycompose_codegen.emit.values import dependency_closure

    narrowed["valueTypes"] = dependency_closure(narrowed, values)
    return narrowed


def app_components(path: Path | None) -> dict[str, Any]:
    """The components an app's own libraries bring, from its lock slice.

    Args:
        path: The app's lock slice, or None when the app declares no libraries.

    Returns:
        Component entries by name; none without a slice.

    Raises:
        AppCodegenError: If the slice is not valid JSON.
    """
    if path is None or not path.is_file():
        return {}
    try:
        components: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))[
            "components"
        ]
    except (json.JSONDecodeError, KeyError) as exc:
        raise AppCodegenError(f"invalid lock slice {path}: {exc}") from exc
    return components


def with_app_lock(registry: dict[str, Any], own: dict[str, Any]) -> dict[str, Any]:
    """The catalog an app builds against: the library's plus its own components.

    Args:
        registry: The library's catalog.
        own: The app's own components (:func:`app_components`).

    Returns:
        The catalog with the app's components merged over the library's.
    """
    if not own:
        return registry
    return with_rules({**registry, "components": {**registry["components"], **own}})


def load_catalog(path: Path) -> dict[str, Any]:
    """Read the catalog lock.

    Args:
        path: The schema file.

    Returns:
        The parsed catalog.

    Raises:
        AppCodegenError: If the file is not valid JSON.
    """
    try:
        return with_rules(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        raise AppCodegenError(f"invalid JSON in {path}: {exc}") from exc
