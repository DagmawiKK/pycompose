"""A package an application ships must not become the home of CLI-only tooling.

``stageRuntime`` stages the runtime package whole: the command line, the catalog
pipeline and the test driver are separate distributions (ADR-0063), so a
tool-only module left inside the runtime would ship to every device, and its
dotted path would mean one thing on a host and another on a device.

``pycompose.extensions`` is where that once happened: planning and evidence
lived beside the runtime and had to be kept out of every APK by name. The rule
below states the structural invariant for ``pycompose.state.disk``, the package
most tempting to grow tool-only helpers -- every module in it is reached from
runtime code, so nothing in it exists only for the CLI.

A repository-wide reachability check is deliberately not attempted. Generated
app slices and host-named entry points import runtime modules that no source
file here imports (``ChaquopyBridge`` names ``pycompose.bridge.runtime``), so a
repo-wide version reports real runtime code as tooling.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "packages/pycompose/src"
"""Where the library's modules live; paths below are relative to it."""
PACKAGE = "pycompose/state/disk/"
TESTS = (ROOT / "tests", *sorted(ROOT.glob("packages/*/tests")))
"""The repository's tests and every distribution's."""
TOOLING = (
    "tools/",
    *(f"{path.relative_to(ROOT).as_posix()}/" for path in TESTS),
)


def _base(path: Path) -> Path:
    return SRC if path.is_relative_to(SRC) else ROOT


def _relative(path: Path) -> str:
    """A POSIX path from the library's source root or the repository's."""
    return path.relative_to(_base(path)).as_posix()


def _sources() -> list[Path]:
    """Every first-party module: the library, its examples, and its tooling."""
    found = []
    for top in (SRC / "pycompose", ROOT / "examples", *TESTS, ROOT / "tools"):
        found.extend(
            path for path in top.rglob("*.py") if "__pycache__" not in path.parts
        )
    return found


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(_base(path)).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imported_names(path: Path) -> set[str]:
    """Every dotted name a file imports, ``from pkg import module`` included."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _resolve(name: str, modules: dict[str, Path]) -> str | None:
    """The first-party module a dotted name refers to, if there is one."""
    if name in modules:
        return name
    parts = name.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        candidate = ".".join(parts[:cut])
        if candidate in modules:
            return candidate
    return None


def _runtime_caller(importer: str) -> bool:
    """True when an importer shows real runtime need, not a CLI or a test."""
    return not importer.startswith(TOOLING) and not importer.startswith(PACKAGE)


def test_no_module_on_disk_is_reached_only_by_tooling() -> None:
    """A module only the CLI imports belongs to the CLI, not to the runtime.

    Reachability starts from callers *outside* the package, so a module cannot
    keep itself alive by having a sibling import it, and never counts tests or
    tools as a reason to ship.
    """
    modules = {
        _module_name(path): path
        for path in _sources()
        if _relative(path).startswith("pycompose/")
    }
    inside = {
        name for name, path in modules.items() if _relative(path).startswith(PACKAGE)
    }
    assert inside, "no modules under pycompose/state/disk; this guard no longer applies"

    importers: defaultdict[str, set[str]] = defaultdict(set)
    imports: defaultdict[str, set[str]] = defaultdict(set)
    for path in _sources():
        importer = _module_name(path)
        for name in _imported_names(path):
            target = _resolve(name, modules)
            if target is None or target == importer:
                continue
            importers[target].add(_relative(path))
            imports[importer].add(target)

    reached = {name for name in inside if any(map(_runtime_caller, importers[name]))}
    frontier = list(reached)
    while frontier:
        for target in imports[frontier.pop()] & inside:
            if target not in reached:
                reached.add(target)
                frontier.append(target)

    unreached = sorted(inside - reached)
    assert not unreached, (
        f"{unreached} are reached only from the CLI or from tests, so every APK "
        "would carry modules no device calls; move them to pycompose-cli"
    )
