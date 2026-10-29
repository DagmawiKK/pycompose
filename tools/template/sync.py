#!/usr/bin/env python3
"""Assemble the package's copied assets from their sources; never committed.

The wheel carries copies of files whose one source lives elsewhere in the
repository: the Android scaffold (``android/`` minus what stays with the
library, plus the template's own files in ``templates/overlay``), the extraction
module ``pycompose add`` lends an app, and the catalog lock and wire schema.
They are assembled here -- by the build backend for every wheel, sdist and
editable install, and by the test session -- so git holds each file once.

    python tools/template/sync.py           # assemble
    python tools/template/sync.py --check   # list what assembling would change
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Build/cache outputs, machine-local configuration and stale bytecode are never
# shipped; __pycache__ would otherwise leak a host-specific .pyc into the APK.
EXCLUDED = frozenset(
    {
        ".gradle",
        ".kotlin",
        ".idea",
        "build",
        "local.properties",
        "__pycache__",
        # Build-time tooling for developing the schema: the dump tasks read
        # :renderer's classpath and the closure file pins what they may scan.
        # They exist only for the repo's own tooling -- a scaffolded app is
        # handed generated code, and never regenerates the catalog.
        "compose-extract",
        "compose-closure.json",
        "tools",
        # The sample host names itself; a scaffolded app gets its launcher
        # label from resources/strings.json as a generated string instead, so
        # this file would collide with that app_name and is never shipped.
        "pycompose_app.xml",
        # The sample's own strings and the keep rule for them: the framework's
        # resource tests read them; an app ships its own resources instead.
        "pycompose_demo.xml",
        "pycompose_keep.xml",
    }
)

# Files and directories the template deliberately lacks, matched as path tails
# rather than parts: a wider rule (say, any part named "generated") would also
# swallow some future shipping file, silently narrowing what the parity test
# guards. The `generated` trees are the catalog the modules used to carry --
# `pycompose build` regenerates the app's slice into .pycompose/generated
# instead (ADR-0014) -- and `src/test` is every module's own test tree, which
# compiles against that full catalog a scaffolded app does not have.
EXCLUDED_SUFFIXES = (
    Path("com/pycompose/ir/generated"),
    Path("com/pycompose/renderer/generated"),
    Path("com/pycompose/host/ui/GeneratedAdapters.kt"),
    Path("com/pycompose/host/GeneratedPreviews.kt"),
    Path("src/test"),
    # The sample a raw Gradle build of the framework runs, and its asset: an
    # app's build always names the app's own source, so a scaffold needs neither.
    Path("python"),
    Path("assets/demo"),
)


def is_excluded(relative: Path) -> bool:
    """Report whether a module path stays with the library, not the template.

    Both callers pass paths rooted differently -- ``sync.py`` walks ``android/``
    and the parity test walks a module's ``src/main`` -- so entries are matched
    against the tail of the path and each of its parents.

    Args:
        relative: Path below ``android/`` or below a module's ``src/main``.

    Returns:
        True when neither tool should require a template counterpart.
    """
    if EXCLUDED.intersection(relative.parts):
        return True
    candidates = (relative, *relative.parents)
    return any(
        candidate.parts[-len(suffix.parts) :] == suffix.parts
        for candidate in candidates
        for suffix in EXCLUDED_SUFFIXES
    )


EXTRACTOR = ("compose-extract", "compose-closure.json")
"""What ``pycompose add`` copies into an app's Android project to extract its
libraries (plan 31 §16.3): the extraction module and the default closure. They
ship as their own asset, never in the scaffold, so an app carries them only
while ``add`` runs."""


PACKAGE = ROOT / "packages/pycompose/src/pycompose"
TEMPLATES = PACKAGE / "templates"
OVERLAY = TEMPLATES / "overlay"
"""The template's own files: what a scaffolded app has that ``android/`` lacks."""

COPIES = {
    PACKAGE / "contract/catalog.lock.json": ROOT / "schema/catalog.lock.json",
    PACKAGE / "schema/ir.schema.json": ROOT / "schema/ir.schema.json",
}
"""Single files the package carries, by their source."""


def _tree(source: Path, skip: Callable[[Path], bool]) -> dict[Path, Path]:
    """Every shipped file below ``source``, by its path relative to it."""
    if source.is_file():
        return {Path(): source}
    return {
        path.relative_to(source): path
        for path in sorted(source.rglob("*"))
        if path.is_file() and not skip(path.relative_to(source))
    }


def plan() -> dict[Path, dict[Path, Path]]:
    """What each assembled directory holds: its files, by their sources.

    Returns:
        Per target directory (or single file), relative paths to source files.

    Raises:
        ValueError: An overlay file would shadow a scaffold file.
    """
    android = _tree(ROOT / "android", is_excluded)
    overlay = _tree(OVERLAY, lambda _: False)
    if shadowed := sorted(str(p) for p in android.keys() & overlay.keys()):
        raise ValueError(f"overlay shadows android/: {', '.join(shadowed)}")
    built = {"build", ".gradle", ".kotlin"}
    targets: dict[Path, dict[Path, Path]] = {TEMPLATES / "android": android | overlay}
    for name in EXTRACTOR:
        targets[TEMPLATES / "extract" / name] = _tree(
            ROOT / "android" / name,
            lambda relative: bool(built & set(relative.parts)),
        )
    for target, source in COPIES.items():
        targets[target] = {Path(): source}
    return targets


def assemble(check: bool = False) -> list[str]:
    """Write the assembled assets, or list what writing them would change.

    A directory is assembled whole: a file no source produces any more is
    removed, so a deleted scaffold file never lingers in the wheel.

    Args:
        check: Report differences without writing.

    Returns:
        The paths that differ, are missing, or are stale, relative to the root.
    """
    changed = []
    for target, files in plan().items():
        wanted = {target / relative if relative.parts else target for relative in files}
        stale = (
            sorted(p for p in target.rglob("*") if p.is_file() and p not in wanted)
            if target.is_dir()
            else []
        )
        for path in stale:
            changed.append(path.relative_to(ROOT).as_posix())
            if not check:
                path.unlink()
        if not check and target.is_dir():
            # A folder its removed files leave empty would still be copied into
            # every new project; deepest first, so emptied parents go too.
            for folder in sorted(target.rglob("*"), key=lambda p: -len(p.parts)):
                if folder.is_dir() and not any(folder.iterdir()):
                    folder.rmdir()
        for relative, source in files.items():
            destination = target / relative if relative.parts else target
            contents = source.read_bytes()
            if destination.is_file() and destination.read_bytes() == contents:
                continue
            changed.append(destination.relative_to(ROOT).as_posix())
            if not check:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(contents)
                destination.chmod(source.stat().st_mode & 0o777)
    return changed


def main() -> int:
    """Assemble the package assets, or report what is out of date."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    changed = assemble(check=args.check)
    if changed:
        print("\n".join(changed))
    return int(args.check and bool(changed))


if __name__ == "__main__":
    raise SystemExit(main())
