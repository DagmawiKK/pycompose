#!/usr/bin/env python3
"""Mirror the canonical Android scaffold into versioned package assets.

Build/cache outputs and machine-local configuration are never shipped. Existing
Python entrypoint/resources remain template-owned and are not touched here.
"""

from __future__ import annotations

import argparse
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
        # Build-time tools for developing the schema. They read :renderer's
        # classpath and exist only for the repo's own tooling -- a scaffolded
        # app is handed generated code, and never regenerates the catalog.
        "dump-compose-api.gradle.kts",
        "dump-compose-defaults.gradle.kts",
    }
)


def main() -> int:
    """Copy native scaffold bytes or report drift without changing files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    source = ROOT / "android"
    target = ROOT / "pycompose/templates/android"
    changed = []
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if not path.is_file() or EXCLUDED.intersection(relative.parts):
            continue
        destination = target / relative
        contents = path.read_bytes()
        if destination.is_file() and destination.read_bytes() == contents:
            continue
        changed.append(relative.as_posix())
        if not args.check:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(contents)
            if path.name == "gradlew":
                destination.chmod(0o755)
    if changed:
        print("\n".join(changed))
    return int(args.check and bool(changed))


if __name__ == "__main__":
    raise SystemExit(main())
