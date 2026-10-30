"""Handlers for the commands that make and check an app's project.

``main`` owns the parser; these turn each parsed command into its effect and
print the outcome.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from pycompose_cli import console
from pycompose_cli.project import load_project
from pycompose_cli.project.prebuild import explain, prebuild
from pycompose_cli.project.toolchain import setup


def add_command(args: argparse.Namespace) -> int:
    # The compiler is imported only when a library is added: no other command
    # pays for it.
    from pycompose_cli.commands.add import add_library

    report = add_library(load_project(Path.cwd()), args.coordinate)
    for name in report.promoted + report.overloads:
        console.ok(f"{name}: exposed")
    for name, reason in sorted(report.refused.items()):
        console.warn(f"{name}: refused -- {reason}")
    console.notice("Import exposed components from m3; pycompose build regenerates it.")
    return 0


def check_command(_args: argparse.Namespace) -> int:
    from pycompose_cli.commands.check import check

    started = time.monotonic()
    problems = check(Path.cwd())
    for problem in problems:
        console.warn(f"{problem.where}: {problem.message} -- {problem.fix}")
    elapsed = time.monotonic() - started
    if problems:
        console.notice(f"{len(problems)} problems in {elapsed:.1f}s")
        return 1
    console.ok(f"No problems found in {elapsed:.1f}s")
    return 0


def render_command(args: argparse.Namespace) -> int:
    from pycompose_cli.commands.render import render

    for image in render(load_project(Path.cwd()), args.snapshots, args.out):
        console.ok(f"{image} and {image.with_suffix('').name}.semantics.json")
    return 0


def prebuild_command(_args: argparse.Namespace) -> int:
    changed = prebuild(load_project(Path.cwd()))
    for name in changed:
        console.line(name)
    console.ok(f"Android project generated; {len(changed)} files changed")
    return 0


def explain_command(args: argparse.Namespace) -> int:
    for source in explain(load_project(Path.cwd()), args.path):
        console.line(source)
    return 0


def migrate_command(_args: argparse.Namespace) -> int:
    from pycompose_cli.commands.migrate import migrate

    found = migrate(load_project(Path.cwd()))
    for refusal in found.refused:
        console.warn(refusal)
    if found.refused:
        console.notice("Nothing changed; give these a config key or a fragment.")
        return 1
    for name in found.fragments:
        console.line(f"resources/android/res/{name}: kept as a fragment")
    if found.icon is not None:
        console.line("icon.svg: the launcher icon, as [app] icon")
    console.ok("The Android project is now generated on every build")
    return 0


def dev_client_command(args: argparse.Namespace) -> int:
    from pycompose_cli.devloop.dev_client import dev_client

    console.ok(f"Dev client: {dev_client(rebuild=args.rebuild)}")
    return 0


def bench_command(args: argparse.Namespace) -> int:
    from pycompose_cli.commands.bench import bench

    count, summary = bench(device=args.device, keys=args.keys, interval=args.interval)
    console.line(f"{count} passes for {args.keys} keystrokes (ms)")
    console.line(f"{'stage':<10}{'p50':>9}{'p95':>9}{'max':>9}")
    for stage, values in summary.items():
        console.line(
            f"{stage:<10}"
            + "".join(f"{values[key]:>9.1f}" for key in ("p50", "p95", "max"))
        )
    return 0


def setup_command(_args: argparse.Namespace) -> int:
    setup()
    console.ok("Toolchain installed; pycompose doctor checks it")
    return 0
