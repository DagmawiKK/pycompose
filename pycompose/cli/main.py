"""PyCompose command entry points; development commands land incrementally."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pycompose.cli.init import InitError, init_project
from pycompose.version import __version__


def main(argv: list[str] | None = None) -> int:
    """Run a CLI command and report failures without a Python traceback.

    Args:
        argv: CLI arguments, or None to read sys.argv.

    Returns:
        Zero on successful initialization or a warned re-init; two on errors.
    """
    parser = argparse.ArgumentParser(
        prog="pycompose", description="Python UI apps for Android"
    )
    parser.add_argument(
        "--version", action="version", version=f"PyCompose {__version__}"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser(
        "init", help="Create a project from packaged template assets"
    )
    init.add_argument("name", help="New project directory name")
    commands.add_parser("run", help="Build, install and launch (not implemented yet)")
    build = commands.add_parser(
        "build", help="Package an Android app (not implemented yet)"
    )
    build.add_argument("format", nargs="?", choices=("apk", "aab"), default="apk")
    build.add_argument("--release", action="store_true")
    sync = commands.add_parser("sync", help="Sync resources (not implemented yet)")
    sync.add_argument("--check", action="store_true")
    commands.add_parser("doctor", help="Check Android tooling (not implemented yet)")
    validate = commands.add_parser(
        "validate", help="Validate IR JSON (not implemented yet)"
    )
    validate.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    if args.command != "init":
        print(f"pycompose {args.command}: not implemented yet", file=sys.stderr)
        return 2
    try:
        path, created, scaffold = init_project(args.name, directory=Path.cwd())
    except (InitError, OSError) as exc:
        print(f"pycompose init: {exc}", file=sys.stderr)
        return 2
    if not created:
        print(f"Warning: {path} already exists; no files changed.", file=sys.stderr)
        return 0
    print(f"Initialized {path}")
    if not scaffold:
        print(
            "Warning: Android scaffold is not included yet; "
            "APK builds require the Android host tickets.",
            file=sys.stderr,
        )
    return 0
