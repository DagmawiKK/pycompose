"""PyCompose command entry points; development commands land incrementally."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from pycompose.cli import console
from pycompose.cli.build import build_project
from pycompose.cli.config import KEYS, Setting, change, settings
from pycompose.cli.doctor import doctor
from pycompose.cli.extensions import show_evidence, show_plan
from pycompose.cli.init import init_project
from pycompose.cli.install import Deploy, install_project
from pycompose.cli.project import ProjectError, load_project
from pycompose.cli.run import run_project
from pycompose.cli.stubs import generate_stubs
from pycompose.cli.sync import sync_resources
from pycompose.cli.validate import validate_file
from pycompose.errors import PyComposeError
from pycompose.version import __version__

_MENU = (
    ("run", "Build, install, launch and watch the app on a device"),
    ("debug", "Build, install and launch the debug app once"),
    ("install", "Install a built APK and verify what the device kept"),
    ("build", "Package an app through its Gradle wrapper"),
    ("release", "Package a signed release artifact"),
    ("config", "Show or change the app name, id and version"),
    ("sync", "Sync named resources into the Android host"),
    ("doctor", "Report Android toolchain and schema compatibility"),
    ("extensions", "Plan explicitly selected extension capabilities"),
    ("validate", "Validate IR JSON against the registry and wire schema"),
    ("stubs", "Print optional module type stubs"),
    ("init", "Create a project from packaged template assets"),
)


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
    init.add_argument(
        "--native",
        action="store_true",
        help="Expose Android sources at the project root",
    )
    run = commands.add_parser(
        "run", help="Build, install, launch, and watch a debug app"
    )
    run.add_argument("--device", help="ADB serial number")
    run.add_argument(
        "--port", type=int, default=0, help="Loopback server port (default: automatic)"
    )
    build = commands.add_parser(
        "build", help="Package an Android app through its Gradle wrapper"
    )
    build.add_argument("format", nargs="?", choices=("apk", "aab"), default="apk")
    build.add_argument("--release", action="store_true")
    install = commands.add_parser(
        "install", help="Install a built APK and verify it on the device"
    )
    install.add_argument(
        "--release", action="store_true", help="Build the release variant first"
    )
    install.add_argument("--device", help="ADB serial number")
    install.add_argument(
        "--launch", action="store_true", help="Start the app after installing"
    )
    debug = commands.add_parser(
        "debug", help="Build, install and launch the debug app (install --launch)"
    )
    debug.add_argument("--device", help="ADB serial number")
    debug.add_argument(
        "--no-launch", action="store_true", help="Install without starting the app"
    )
    release = commands.add_parser("release", help="Package a signed release artifact")
    release.add_argument("format", nargs="?", choices=("apk", "aab"), default="apk")
    release.add_argument(
        "--install", action="store_true", help="Install the release APK on a device"
    )
    config = commands.add_parser(
        "config", help="Show or change the app name, id and version"
    )
    config.add_argument(
        "action",
        nargs="?",
        choices=("show", "set"),
        help="show settings or rewrite one",
    )
    config.add_argument("key", nargs="?", help=f"setting to rewrite: {', '.join(KEYS)}")
    config.add_argument("value", nargs="?", help="new value for the setting")
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
    stubs = commands.add_parser(
        "stubs", help="Print optional module type stubs without importing app code"
    )
    stubs.add_argument("path", type=Path)
    extensions = commands.add_parser(
        "extensions", help="Plan extensions without importing their implementations"
    )
    extensions.add_argument(
        "action", choices=("plan", "evidence"), nargs="?", default="plan"
    )
    return parser


def _validate(args: argparse.Namespace) -> int:
    validate_file(args.path)
    console.line(f"Valid IR: {args.path}")
    return 0


def _stubs(args: argparse.Namespace) -> int:
    print(generate_stubs(args.path), end="")
    return 0


def _extensions(args: argparse.Namespace) -> int:
    project = load_project(Path.cwd())
    if args.action == "evidence":
        return show_evidence(project)
    return show_plan(project)


def _build(args: argparse.Namespace) -> int:
    outputs = build_project(
        load_project(Path.cwd()), kind=args.format, release=args.release
    )
    for path in outputs:
        console.line(f"Built artifact: {path}")
    return 0


def _report(deploy: Deploy) -> None:
    """Print what an install did, in a form a script can read.

    Args:
        deploy: Outcome of the install to report.
    """
    console.ok(f"Installed {deploy.package} on {deploy.device}")
    console.line(f"artifact: {deploy.artifact}")
    console.line(f"md5: {deploy.digest}")
    if deploy.verified:
        console.ok("Digest matches on the device")
    else:
        console.warn("the device reported no digest; the install is unverified")
    if deploy.launch_ms is not None:
        console.ok(f"Launched in {deploy.launch_ms} ms")


def _install(args: argparse.Namespace) -> int:
    deploy = install_project(
        load_project(Path.cwd()),
        release=args.release,
        device=args.device,
        launch=args.launch,
    )
    _report(deploy)
    return 0


def _debug(args: argparse.Namespace) -> int:
    deploy = install_project(
        load_project(Path.cwd()), device=args.device, launch=not args.no_launch
    )
    _report(deploy)
    return 0


def _release(args: argparse.Namespace) -> int:
    project = load_project(Path.cwd())
    outputs = build_project(project, kind=args.format, release=True)
    for path in outputs:
        console.line(f"Built artifact: {path}")
    if not args.install:
        return 0
    if args.format != "apk" or len(outputs) != 1:
        raise ProjectError(
            "release --install needs a single APK; build one with pycompose release apk"
        )
    _report(install_project(project, release=True, artifact=outputs[0]))
    return 0


def _show_settings(current: tuple[Setting, ...]) -> None:
    """Print the settings as a table.

    Args:
        current: Settings to display, in declaration order.
    """
    view = console.table("Setting", "Value", "Source")
    for setting in current:
        view.add_row(
            console.plain(setting.key),
            console.plain(setting.value or "-"),
            console.plain(setting.source),
        )
    console.render(view)


def _config(args: argparse.Namespace) -> int:
    project = load_project(Path.cwd())
    current = settings(project)
    if args.action == "set":
        if not args.key or args.value is None:
            raise ProjectError(
                "config set takes a setting and a value; "
                "pycompose config show lists them"
            )
        written = change(project, args.key, args.value)
        console.ok(f"{written.key} = {written.value}")
        console.line(f"source: {written.source}")
        console.notice("Install the change with: pycompose debug")
        return 0
    _show_settings(current)
    if args.action == "show" or not console.interactive():
        console.notice("Change one with: pycompose config set <setting> <value>")
        return 0
    if not console.confirm("Change the app name or version?", default=False):
        return 0
    for setting in current:
        value = console.ask(setting.key, default=setting.value or None)
        if value != setting.value:
            change(project, setting.key, value)
    # Project.config is a frozen snapshot of the file change() rewrote, so the
    # refreshed table is read back from disk rather than from the loaded copy.
    _show_settings(settings(load_project(Path.cwd())))
    console.notice("Install the change with: pycompose debug")
    return 0


def _doctor(_args: argparse.Namespace) -> int:
    checks = doctor(Path.cwd())
    for check in checks:
        console.check_line(check.ok, check.name, check.detail)
    failed = [check for check in checks if not check.ok]
    if failed:
        console.notice(f"{len(failed)} of {len(checks)} checks failed")
        return 2
    return 0


def _sync(args: argparse.Namespace) -> int:
    changed = sync_resources(load_project(Path.cwd()), check=args.check)
    if not changed:
        console.line("Resources up to date")
    else:
        for name in changed:
            console.line(name)
    return 1 if args.check and changed else 0


def _run(args: argparse.Namespace) -> int:
    try:
        run_project(load_project(Path.cwd()), device=args.device, port=args.port)
    except KeyboardInterrupt:
        return 0
    return 0


def _init(args: argparse.Namespace) -> int:
    path, created, scaffold = init_project(
        args.name, directory=Path.cwd(), native=args.native
    )
    if not created:
        console.warn(f"{path} already exists; no files changed.")
        return 0
    console.ok(f"Initialized {path}")
    if not scaffold:
        console.warn(
            "Android scaffold is not included yet; "
            "APK builds require the Android host tickets."
        )
    console.notice(f"Next: cd {args.name} && pycompose run")
    return 0


def _chooser() -> list[str]:
    """Compose a command line interactively, for a bare ``pycompose``.

    Returns:
        Arguments for the parser, as if they had been typed.
    """
    menu = console.table("Command", "What it does")
    for name, description in _MENU:
        menu.add_row(console.plain(name), console.plain(description))
    console.render(menu)
    command = console.ask(
        "Command", choices=[name for name, _ in _MENU], default="doctor"
    )
    if command == "init":
        return ["init", console.ask("Project directory")]
    if command in {"validate", "stubs"}:
        return [command, console.ask("Path")]
    return [command]


def main(argv: list[str] | None = None) -> int:
    """Run a CLI command and report domain failures without a traceback.

    Args:
        argv: CLI arguments, or None to read sys.argv.

    Returns:
        Zero on success, one on check drift, or two on command errors.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments and console.interactive():
        try:
            arguments = _chooser()
        except (EOFError, KeyboardInterrupt):
            console.notice("aborted")
            return 2
    args = _parser().parse_args(arguments)
    handlers = {
        "init": _init,
        "sync": _sync,
        "validate": _validate,
        "build": _build,
        "install": _install,
        "debug": _debug,
        "release": _release,
        "config": _config,
        "doctor": _doctor,
        "run": _run,
        "stubs": _stubs,
        "extensions": _extensions,
    }
    try:
        return handlers[args.command](args)
    except (PyComposeError, OSError, subprocess.TimeoutExpired) as exc:
        console.error(args.command, str(exc))
        return 2
    except (EOFError, KeyboardInterrupt):
        console.notice("aborted")
        return 2
