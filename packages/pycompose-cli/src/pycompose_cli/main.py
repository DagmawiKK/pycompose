"""PyCompose command entry points; development commands land incrementally."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

from pycompose.errors import PyComposeError
from pycompose.version import __version__
from pycompose_cli import console, project_commands
from pycompose_cli.build import build_project
from pycompose_cli.config import KEYS, Setting, change, settings
from pycompose_cli.doctor import doctor
from pycompose_cli.init import init_project
from pycompose_cli.install import Deploy, install_project
from pycompose_cli.prebuild import generated
from pycompose_cli.project import ProjectError, load_project
from pycompose_cli.run import run_project
from pycompose_cli.stubs import generate_stubs
from pycompose_cli.sync import sync_resources
from pycompose_cli.validate import validate_file

_MENU = (
    ("run", "Build, install, launch and watch the app on a device"),
    ("debug", "Build, install and launch the debug app once"),
    ("install", "Install a built APK and verify what the device kept"),
    ("build", "Package an app through its Gradle wrapper"),
    ("release", "Package a signed release artifact"),
    ("config", "Show or change the app name, id and version"),
    ("add", "Wrap a Compose library from Maven into the app's catalog"),
    ("check", "Find what a build or the store would refuse, without either"),
    ("render", "Screenshot the app and dump its semantics, with no device"),
    ("prebuild", "Generate the Android project from the app and show what changed"),
    ("explain", "Say which config keys produced a generated Android file"),
    ("setup", "Install the pinned JDK and Android SDK"),
    ("dev-client", "Build the prebuilt dev client once for this PyCompose"),
    ("bench", "Type into the running app and report each pass stage's time"),
    ("migrate", "Move an app-owned Android project to a generated one"),
    ("sync", "Sync named resources into the Android host"),
    ("doctor", "Report Android toolchain and schema compatibility"),
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
    init.add_argument(
        "--template",
        choices=("blocks", "viewmodel"),
        default="blocks",
        help="Start from components and functions (blocks), or from a view "
        "model drawing native components (viewmodel)",
    )
    _device_parsers(commands)
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
    add = commands.add_parser(
        "add", help="Wrap a Compose library from Maven into the app's catalog"
    )
    add.add_argument("coordinate", help="group:artifact or group:artifact:version")
    commands.add_parser(
        "check", help="Find what a build or the store would refuse, without either"
    )
    render = commands.add_parser(
        "render", help="Screenshot the app and dump its semantics, with no device"
    )
    render.add_argument("snapshots", nargs="*", type=Path, help="snapshot JSON files")
    render.add_argument("--out", type=Path, default=Path("screenshots"))
    commands.add_parser(
        "prebuild",
        help="Generate the Android project from the app and show what changed",
    )
    explain = commands.add_parser(
        "explain", help="Say which config keys produced a generated Android file"
    )
    explain.add_argument("path", help="a file of .pycompose/android")
    commands.add_parser("setup", help="Install the pinned JDK and Android SDK")
    client = commands.add_parser(
        "dev-client", help="Build the prebuilt dev client once for this PyCompose"
    )
    client.add_argument("--rebuild", action="store_true")
    commands.add_parser(
        "migrate", help="Move an app-owned Android project to a generated one"
    )
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
    return parser


def _device_parsers(commands: argparse._SubParsersAction[Any]) -> None:
    """Add the commands that drive an app running on a device."""
    run = commands.add_parser(
        "run", help="Build, install, launch, and watch a debug app"
    )
    run.add_argument("--device", help="ADB serial number")
    run.add_argument(
        "--port", type=int, default=0, help="Loopback server port (default: automatic)"
    )
    run.add_argument(
        "--dev-client",
        action="store_true",
        help="Run on the prebuilt dev client: no Gradle build of the app",
    )
    bench = commands.add_parser(
        "bench", help="Type into the running app and report each pass stage's time"
    )
    bench.add_argument("--device", help="ADB serial number")
    bench.add_argument("--keys", type=int, default=30, help="keystrokes to send")
    bench.add_argument(
        "--interval", type=float, default=0.15, help="seconds between keystrokes"
    )


def _validate(args: argparse.Namespace) -> int:
    validate_file(args.path)
    console.line(f"Valid IR: {args.path}")
    return 0


def _stubs(args: argparse.Namespace) -> int:
    print(generate_stubs(args.path), end="")
    return 0


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
    project = load_project(Path.cwd())
    if generated(project):
        if args.check:
            console.line("The Android project is generated on every build")
            return 0
        return project_commands.prebuild_command(args)
    changed = sync_resources(project, check=args.check)
    if not changed:
        console.line("Resources up to date")
    else:
        for name in changed:
            console.line(name)
    return 1 if args.check and changed else 0


def _run(args: argparse.Namespace) -> int:
    try:
        run_project(
            load_project(Path.cwd()),
            device=args.device,
            port=args.port,
            dev_client=args.dev_client,
        )
    except KeyboardInterrupt:
        return 0
    return 0


def _init(args: argparse.Namespace) -> int:
    path, created, scaffold = init_project(
        args.name, directory=Path.cwd(), native=args.native, starter=args.template
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
    if command == "add":
        return ["add", console.ask("Maven coordinate (group:artifact[:version])")]
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
        "add": project_commands.add_command,
        "check": project_commands.check_command,
        "render": project_commands.render_command,
        "prebuild": project_commands.prebuild_command,
        "explain": project_commands.explain_command,
        "setup": project_commands.setup_command,
        "dev-client": project_commands.dev_client_command,
        "bench": project_commands.bench_command,
        "migrate": project_commands.migrate_command,
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
    }
    try:
        return handlers[args.command](args)
    except (PyComposeError, OSError, subprocess.TimeoutExpired) as exc:
        console.error(args.command, str(exc))
        return 2
    except (EOFError, KeyboardInterrupt):
        console.notice("aborted")
        return 2
