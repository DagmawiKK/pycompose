"""Check recorded host runs against the Mailbox model (trace validation).

A run is a JSON list of the events the host's queue produced, in order:
``{"event": "post" | "process", "kind": "report", "w": ..., "v": ...}``,
``{"event": "post" | "process", "kind": "intent", "id": ...}`` and
``{"event": "pull"}``. Every run in the directory is checked in one TLC pass
by ``MailboxTrace``; a run the model cannot follow fails with TLC's trace to the
event where it stopped.

Usage:
    python tools/spec/trace.py android/host/build/traces
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from check import HERE, tools

FIELDS = ("event", "kind", "w", "v", "id")


def _string(value: object) -> str:
    return json.dumps(str(value))


def _record(event: dict[str, object]) -> str:
    # Every event has every field, so the model reads any of them on any event.
    fields = ", ".join(f"{k} |-> {_string(event.get(k, ''))}" for k in FIELDS)
    return f"[{fields}]"


def _set(values: set[str]) -> str:
    return "{" + ", ".join(_string(v) for v in sorted(values)) + "}"


def trace_data(runs: list[list[dict[str, object]]]) -> str:
    """Return the ``TraceData`` module: the runs and the constants they need.

    Args:
        runs: Each run's events, in order.

    Returns:
        TLA+ source.
    """
    posted = [e for run in runs for e in run if e["event"] == "post"]
    reports = [e for e in posted if e["kind"] == "report"]
    most = max(sum(e in reports for e in run) for run in runs)
    traces = ",\n    ".join(
        "<<" + ", ".join(_record(e) for e in run) + ">>" for run in runs
    )
    return "\n".join(
        [
            "---- MODULE TraceData ----",
            "EXTENDS Sequences",
            f"Traces == <<\n    {traces}\n    >>",
            f"TraceWidgets == {_set({str(e['w']) for e in reports})}",
            f"TraceValues == {_set({str(e['v']) for e in reports})}",
            "TraceIntents == "
            + _set({str(e["id"]) for e in posted if e["kind"] == "intent"}),
            f"TraceMaxReports == {most}",
            "====",
            "",
        ]
    )


CONFIG = """\
CONSTANTS
    Widgets <- TraceWidgets
    Values <- TraceValues
    Intents <- TraceIntents
    MaxReports <- TraceMaxReports
INIT TraceInit
NEXT TraceNext
INVARIANTS
    TypeOK
    IntentsNeverDropped
    ReportsPrecedeIntents
    MailboxBounded
    HostNeverAhead
"""


def validate(runs: list[list[dict[str, object]]]) -> subprocess.CompletedProcess[str]:
    """Run TLC over every run at once.

    Args:
        runs: Each run's events, in order.

    Returns:
        TLC's finished process; it succeeded when no run was rejected.
    """
    with tempfile.TemporaryDirectory() as work:
        folder = Path(work)
        for module in ("Mailbox.tla", "MailboxTrace.tla"):
            shutil.copy(HERE / module, folder / module)
        (folder / "TraceData.tla").write_text(trace_data(runs))
        (folder / "MailboxTrace.cfg").write_text(CONFIG)
        return subprocess.run(
            [
                "java",
                "-XX:+UseParallelGC",
                "-cp",
                str(tools()),
                "tlc2.TLC",
                "-metadir",
                str(folder / "states"),
                "-config",
                "MailboxTrace.cfg",
                "MailboxTrace.tla",
            ],
            cwd=folder,
            capture_output=True,
            text=True,
            check=False,
        )


def main() -> int:
    """Validate every recorded run in the directory given.

    Returns:
        0 when the model accepts every run, 1 otherwise.

    Raises:
        SystemExit: With the usage, when no directory is given.
    """
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    files = sorted(Path(sys.argv[1]).glob("*.json"))
    if not files:
        print(f"trace: no recorded runs in {sys.argv[1]}", file=sys.stderr)
        return 1
    runs = [json.loads(path.read_text()) for path in files]
    result = validate(runs)
    if result.returncode != 0 or "No error has been found" not in result.stdout:
        print(result.stdout + result.stderr, file=sys.stderr)
        # The last state TLC printed is where the rejected run stopped.
        where = dict(re.findall(r"^/\\ ([tl]) = (\d+)$", result.stdout, re.M))
        if where:
            run, event = int(where["t"]) - 1, int(where["l"]) - 1
            print(
                f"trace: {files[run].name} event {event} is not a step of "
                f"Mailbox: {json.dumps(runs[run][event])}",
                file=sys.stderr,
            )
        return 1
    print(f"trace: Mailbox accepts all {len(runs)} recorded runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
