"""Run the component compiler.

    python -m tools.composegen generate          # write lock, signatures, report
    python -m tools.composegen generate --check  # fail if either is stale
    python -m tools.composegen diff --base main  # classify changes since a ref

Run ``./gradlew dumpComposeApi dumpComposeDefaults`` in android/ first: the
compiler reads the pinned evidence they extract. Then run
``tools/schema/gen.py``: it copies the lock into the package and regenerates
everything the lock drives.
"""

from __future__ import annotations

import argparse
import difflib
import json
import subprocess
import sys
from pathlib import Path

if __package__ in {None, ""}:  # pragma: no cover - only when run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.composegen import signatures
from tools.composegen.diff import classify, load_approvals, unapproved
from tools.composegen.lock import LOCK, ROOT, Report, dumps, generate
from tools.composegen.policy import load
from tools.schema.classpath_dump import DUMP_DIR, inventory

REPORT = DUMP_DIR / "composegen-report.md"
SIGNATURES = ROOT / "schema/signatures"


def render(report: Report) -> str:
    """Render the run's report for review.

    Args:
        report: What the run found.

    Returns:
        Markdown: coverage and held components with reasons.
    """
    lines = [
        "# Component compiler report",
        "",
        f"- Derived from the pin: {len(report.derived)}",
        f"- Held whole by policy: {len(report.manual)}",
        "",
        "## Held whole, by reason",
        "",
        *(f"- {name}: {reason}" for name, reason in sorted(report.manual.items())),
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Generate or check the lock, or classify its changes since a ref.

    Args:
        argv: Command-line arguments.

    Returns:
        A process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["generate", "diff"])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--base", default="HEAD", help="git ref to compare with")
    args = parser.parse_args(argv)
    if args.command == "diff":
        return _diff(args.base)
    try:
        lock, report = generate(load())
        found = inventory(DUMP_DIR)
    except (OSError, ValueError) as exc:
        print(f"composegen: {exc}", file=sys.stderr)
        return 2
    for error in report.errors:
        print(f"composegen: {error}", file=sys.stderr)
    if report.errors:
        return 1
    outputs = {
        LOCK: dumps(lock),
        SIGNATURES / f"{found.bom}.txt": signatures.render(found),
    }
    if args.check:
        stale = [
            path
            for path, text in outputs.items()
            if not path.is_file() or path.read_text(encoding="utf-8") != text
        ]
        for path in stale:
            print(f"composegen: {path} is stale; run generate", file=sys.stderr)
        return 1 if stale else 0
    for path, text in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render(report), encoding="utf-8")
    print(
        f"composegen: {len(report.derived)} derived, {len(report.manual)} held; "
        f"report at {REPORT}"
    )
    return 0


def _at(ref: str, path: Path) -> str | None:
    """A committed file's text at a ref, or None where it did not exist."""
    shown = subprocess.run(
        ["git", "show", f"{ref}:{path.relative_to(ROOT).as_posix()}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return shown.stdout if shown.returncode == 0 else None


def _diff(base: str) -> int:
    """Print the classified lock diff and the signature diff since ``base``."""
    old = _at(base, LOCK)
    if old is None:
        print(f"composegen: no lock at {base}; nothing to classify")
        return 0
    changes = classify(json.loads(old), json.loads(LOCK.read_text(encoding="utf-8")))
    for change in changes:
        print(f"{change.kind:10} {change.id}")
    current = sorted(SIGNATURES.glob("*.txt"))
    if current:
        before = _at(base, current[-1])
        if before is None:
            listed = subprocess.run(
                ["git", "ls-tree", "--name-only", base, "schema/signatures/"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            ).stdout.split()
            before = _at(base, ROOT / listed[-1]) if listed else ""
        after = current[-1].read_text(encoding="utf-8")
        sys.stdout.writelines(
            difflib.unified_diff(
                (before or "").splitlines(keepends=True),
                after.splitlines(keepends=True),
                f"{base}:signatures",
                current[-1].name,
                n=0,
            )
        )
    missing, stale = unapproved(changes, load_approvals())
    for change in missing:
        print(
            f"composegen: {change.kind} change needs approval: {change.id}",
            file=sys.stderr,
        )
    for approval in stale:
        print(
            f"composegen: approval names no current change: {approval}", file=sys.stderr
        )
    return 1 if missing or stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
