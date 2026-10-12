"""PyCompose command entry points; development commands land incrementally."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pycompose.cli.build import build_project
from pycompose.cli.doctor import doctor
from pycompose.cli.init import init_project
from pycompose.cli.project import load_project
from pycompose.cli.sync import sync_resources
from pycompose.cli.validate import validate_file
from pycompose.errors import PyComposeError
from pycompose.version import __version__


def _parser() -> argparse.ArgumentParser:
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
        "build", help="Package an Android app through its Gradle wrapper"
    )
    build.add_argument("format", nargs="?", choices=("apk", "aab"), default="apk")
    build.add_argument("--release", action="store_true")
    sync = commands.add_parser(
        "sync", help="Sync named resources into the Android host"
    )
    sync.add_argument("--check", action="store_true")
    commands.add_parser(
        "doctor", help="Report Android toolchain and schema compatibility"
    )
    validate = commands.add_parser(
        "validate", help="Validate IR JSON against the registry and wire schema"
    )
    validate.add_argument("path", type=Path)
    return parser


def _validate(args: argparse.Namespace) -> int:
    validate_file(args.path)
    print(f"Valid IR: {args.path}")
    return 0


def _build(args: argparse.Namespace) -> int:
    outputs = build_project(
        load_project(Path.cwd()), kind=args.format, release=args.release
    )
    for path in outputs:
        print(f"Built artifact: {path}")
    return 0


def _doctor(_args: argparse.Namespace) -> int:
    checks = doctor(Path.cwd())
    for check in checks:
        print(f"{'OK' if check.ok else 'FAIL'} {check.name}: {check.detail}")
    return 0 if all(check.ok for check in checks) else 2


def _sync(args: argparse.Namespace) -> int:
    changed = sync_resources(load_project(Path.cwd()), check=args.check)
    print("Resources up to date" if not changed else "\n".join(changed))
    return 1 if args.check and changed else 0


def _unimplemented(args: argparse.Namespace) -> int:
    print(f"pycompose {args.command}: not implemented yet", file=sys.stderr)
    return 2


def _init(args: argparse.Namespace) -> int:
    path, created, scaffold = init_project(args.name, directory=Path.cwd())
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


def main(argv: list[str] | None = None) -> int:
    """Run a CLI command and report domain failures without a traceback.

    Args:
        argv: CLI arguments, or None to read sys.argv.

    Returns:
        Zero on success, one on check drift, or two on command errors.
    """
    args = _parser().parse_args(argv)
    handlers = {
        "init": _init,
        "sync": _sync,
        "validate": _validate,
        "build": _build,
        "doctor": _doctor,
        "run": _unimplemented,
    }
    try:
        return handlers[args.command](args)
    except (PyComposeError, OSError) as exc:
        print(f"pycompose {args.command}: {exc}", file=sys.stderr)
        return 2
