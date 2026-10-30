#!/usr/bin/env python3
"""Folders under a distribution's source that git no longer tracks anything in.

A package removed from git can leave its folder behind, holding only bytecode
caches. Python still imports such a folder as an empty namespace package, so
an import of the removed name succeeds where it should fail. This lists them.

    python tools/stale_packages.py       # exit 1 and list each stale folder
"""

from __future__ import annotations

import subprocess  # nosec B404 -- git, with fixed arguments
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def stale(root: Path = ROOT) -> list[Path]:
    """Folders under ``packages/*/src`` that hold no tracked file.

    Args:
        root: The checkout to inspect.

    Returns:
        Each stale folder, sorted.
    """
    tracked = subprocess.run(  # nosec B603 B607 -- git, fixed arguments
        ["git", "-C", str(root), "ls-files", "--", "packages/*/src/*"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    kept = {root / parent for name in tracked for parent in Path(name).parents}
    untracked = [
        folder
        for source in root.glob("packages/*/src")
        for folder in source.rglob("*")
        if folder.is_dir() and folder not in kept
    ]
    if not untracked:
        return []
    # A folder git ignores is build output (caches, assembled copies), not stale.
    ignored = subprocess.run(  # nosec B603 B607 -- git, fixed arguments
        ["git", "-C", str(root), "check-ignore", *map(str, untracked)],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.splitlines()
    skip = {Path(line) for line in ignored}
    return sorted(
        folder
        for folder in untracked
        if not any(folder == s or s in folder.parents for s in skip)
    )


def main() -> int:
    """List stale folders; exit 1 when there are any."""
    found = stale()
    for folder in found:
        print(f"stale: {folder.relative_to(ROOT)} holds no tracked file; delete it")
    return int(bool(found))


if __name__ == "__main__":
    raise SystemExit(main())
