"""Run the component compiler.

    python -m tools.composegen generate          # write the lock and the report
    python -m tools.composegen generate --check  # fail if the lock is stale

Run ``./gradlew dumpComposeApi dumpComposeDefaults`` in android/ first: the
compiler reads the pinned evidence they extract. Then run
``tools/schema/gen.py``: it copies the lock into the package and regenerates
everything the lock drives.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:  # pragma: no cover - only when run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.composegen.lock import LOCK, Report, dumps, generate
from tools.composegen.policy import load
from tools.schema.classpath_dump import DUMP_DIR

REPORT = DUMP_DIR / "composegen-report.md"


def render(report: Report) -> str:
    """Render the run's report for review.

    Args:
        report: What the run found.

    Returns:
        Markdown: coverage, held components with reasons, redundant policy.
    """
    lines = [
        "# Component compiler report",
        "",
        f"- Derived from the pin: {len(report.derived)}",
        f"- Held whole by policy: {len(report.manual)}",
        f"- Redundant policy entries: {len(report.redundant)}",
        "",
        "## Held whole, by reason",
        "",
        *(f"- {name}: {reason}" for name, reason in sorted(report.manual.items())),
        "",
        "## Policy the pin already implies",
        "",
        *(f"- {path}" for path in report.redundant),
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Generate or check the lock.

    Args:
        argv: Command-line arguments.

    Returns:
        A process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["generate"])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        lock, report = generate(load())
    except (OSError, ValueError) as exc:
        print(f"composegen: {exc}", file=sys.stderr)
        return 2
    for error in report.errors:
        print(f"composegen: {error}", file=sys.stderr)
    if report.errors:
        return 1
    text = dumps(lock)
    if args.check:
        if not LOCK.is_file() or LOCK.read_text(encoding="utf-8") != text:
            print(f"composegen: {LOCK} is stale; run generate", file=sys.stderr)
            return 1
        return 0
    LOCK.write_text(text, encoding="utf-8")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render(report), encoding="utf-8")
    print(
        f"composegen: {len(report.derived)} derived, {len(report.manual)} held; "
        f"report at {REPORT}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
