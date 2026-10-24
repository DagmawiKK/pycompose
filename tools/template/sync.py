#!/usr/bin/env python3
"""Mirror the canonical Android scaffold into versioned package assets.

Build/cache outputs and machine-local configuration are never shipped. Existing
Python entrypoint/resources remain template-owned and are not touched here.
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


def _mirror(
    source: Path, target: Path, skip: Callable[[Path], bool], check: bool
) -> list[str]:
    """Copy every file under ``source`` to ``target``, or list what differs.

    Args:
        source: A file or directory in ``android/``.
        target: Where its package asset lives.
        skip: Paths below ``source`` that stay with the library.
        check: Report differences without writing.

    Returns:
        The differing paths, relative to ``source``'s parent.
    """
    changed = []
    files = [source] if source.is_file() else sorted(source.rglob("*"))
    for path in files:
        relative = path.relative_to(source)
        if not path.is_file() or skip(relative):
            continue
        destination = target / relative if relative.parts else target
        contents = path.read_bytes()
        if destination.is_file() and destination.read_bytes() == contents:
            continue
        changed.append(path.relative_to(source.parent).as_posix())
        if not check:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(contents)
            if path.name == "gradlew":
                destination.chmod(0o755)
    return changed


def main() -> int:
    """Copy native scaffold bytes or report drift without changing files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    android = ROOT / "android"
    changed = _mirror(
        android, ROOT / "pycompose/templates/android", is_excluded, args.check
    )
    for name in EXTRACTOR:
        changed += _mirror(
            android / name,
            ROOT / "pycompose/templates/extract" / name,
            lambda relative: bool(
                {"build", ".gradle", ".kotlin"} & set(relative.parts)
            ),
            args.check,
        )
    if changed:
        print("\n".join(changed))
    return int(args.check and bool(changed))


if __name__ == "__main__":
    raise SystemExit(main())
