"""The pass-time SLO gate: measure a release pass, fail on a regression over 20%.

A pass is what the user waits for after a tap. ``measure`` times it where it is
deterministic enough to gate on: the notes editor, typed into through a release
bridge on the loop thread, as on a device. ``device`` times the whole of it, tap
to frame, on a device or emulator running the notes app. Timings are only
comparable on one machine, so CI measures the base commit and the change on the
same runner and compares them, rather than against numbers recorded elsewhere.

    python tools/slo.py measure -o after.json
    python tools/slo.py device -o after.json           # the notes app installed
    python tools/slo.py check before.json after.json   # exit 1 on a regression
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TOLERANCE = 0.2
"""A metric may grow by this share before the gate fails."""

FLOOR_MS = 0.05
"""Growth under this many milliseconds is noise, whatever its share."""

NOTES = "com.example.notes"
ACTIVITY = "com.pycompose.host.MainActivity"


def _notes_pass_times(keystrokes: int) -> list[float]:
    """Type into the notes editor through a release bridge; each pass in ms."""
    sys.path[:0] = [str(ROOT / "examples/notes/app"), str(ROOT)]
    import main
    from notes_app.container import AppContainer
    from notes_app.data.notes_repo import MemoryNotesRepo
    from notes_app.domain.models import Note

    from pycompose.app.session import NavigationSession
    from pycompose.bridge import BridgeSurface
    from pycompose.runtime.loop import LoopThread
    from pycompose.state import Store

    def intents(bridge: Any) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []

        def visit(value: object) -> None:
            if isinstance(value, dict):
                if set(value) == {"fields", "intent"}:
                    found.append(value)
                    return
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(json.loads(bridge.expose_latest_snapshot())["root"])
        return found

    def run() -> list[float]:
        notes = [Note(n, f"Note {n}", "body " * 20) for n in range(1, 60)]
        container = AppContainer(MemoryNotesRepo(notes))
        session = NavigationSession(
            main.app, container, "", "", report=lambda *_: None, signal=lambda: None
        )
        bridge = BridgeSurface(
            Store(session.snapshot_state(None)), session, debug=False
        )
        opened = next(i for i in intents(bridge) if i["intent"].endswith("OpenNote"))
        bridge.accept_action(json.dumps({**opened, "payload": {}}))
        title = next(i for i in intents(bridge) if i["intent"].endswith("SetTitle"))
        times = []
        for n in range(keystrokes):
            started = time.perf_counter()
            text = "x" * (n % 40)
            # A pass is what the host does: run the action, then pull.
            bridge.accept_action(json.dumps({**title, "payload": {"value": text}}))
            bridge.expose_envelope(-1)
            times.append((time.perf_counter() - started) * 1000)
        return times

    loop = LoopThread(lambda *_: None)
    try:
        return loop.call(run)
    finally:
        loop.stop()


def measure(*, rounds: int = 5, keystrokes: int = 300) -> dict[str, float]:
    """Measure the pass, keeping each round's best so a busy moment cannot count.

    Args:
        rounds: Independent runs; each statistic keeps its lowest round.
        keystrokes: Passes per round; the first sixth warms up and is dropped.

    Returns:
        Milliseconds: the pass's median and 95th percentile.
    """
    p50s, p95s = [], []
    for _ in range(rounds):
        times = sorted(_notes_pass_times(keystrokes)[keystrokes // 6 :])
        p50s.append(statistics.median(times))
        p95s.append(times[round(0.95 * (len(times) - 1))])
    return {"passP50Ms": round(min(p50s), 4), "passP95Ms": round(min(p95s), 4)}


def _device_bounds(executable: str, serial: str, pattern: str) -> tuple[int, int]:
    """Find the centre of the first on-screen element whose attributes match."""
    from pycompose_cli.devloop.device import adb_command

    for _ in range(20):
        adb_command(executable, "-s", serial, "shell", "uiautomator", "dump")
        dump = adb_command(
            executable, "-s", serial, "shell", "cat", "/sdcard/window_dump.xml"
        )
        for node in re.findall(r"<node [^>]*>", dump):
            if re.search(pattern, node):
                box = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
                if box:
                    x1, y1, x2, y2 = map(int, box.groups())
                    return (x1 + x2) // 2, (y1 + y2) // 2
        time.sleep(0.5)
    raise LookupError(pattern)


def measure_device(
    *, device: str | None = None, rounds: int = 3, keys: int = 40
) -> dict[str, float]:
    """Type into a new note on a device, tap to frame, keeping each round's best.

    The notes app must be installed. It starts from cleared data each round, so
    every round types into the same, empty editor.

    Args:
        device: ADB serial; automatic selection requires one ready device.
        rounds: Independent runs; each statistic keeps its lowest round.
        keys: Keystrokes per round.

    Returns:
        Milliseconds from the keystroke reaching the host to its frame drawn.
    """
    from pycompose_cli.commands.bench import bench
    from pycompose_cli.devloop.device import adb, adb_command, select_device

    executable = adb()
    serial = select_device(executable, device)

    def shell(*args: str) -> None:
        adb_command(executable, "-s", serial, "shell", *args)

    p50s, p95s = [], []
    for _ in range(rounds):
        shell("pm", "clear", NOTES)
        shell(
            "am", "start", "-W", "-n", f"{NOTES}/{ACTIVITY}",
            "--ez", "pycompose.timePasses", "true",
        )  # fmt: skip
        shell(
            "input",
            "tap",
            *map(str, _device_bounds(executable, serial, 'content-desc="New note"')),
        )
        shell("input", "tap", *map(str, _device_bounds(executable, serial, "EditText")))
        time.sleep(1.0)
        _, stages = bench(device=serial, keys=keys)
        p50s.append(stages["total"]["p50"])
        p95s.append(stages["total"]["p95"])
    return {
        "tapToFrameP50Ms": round(min(p50s), 2),
        "tapToFrameP95Ms": round(min(p95s), 2),
    }


def regressions(
    before: dict[str, float],
    after: dict[str, float],
    *,
    tolerance: float = TOLERANCE,
    floor_ms: float = FLOOR_MS,
) -> list[str]:
    """Name every metric that grew by more than ``tolerance``.

    Args:
        before: The base commit's measurement.
        after: The change's measurement.
        tolerance: The share a metric may grow by.
        floor_ms: Growth this small is noise.

    Returns:
        One line per regressed metric; empty when the change passes.
    """
    found = []
    for name, base in sorted(before.items()):
        current = after.get(name)
        if current is None:
            continue
        if current > base * (1 + tolerance) and current - base > floor_ms:
            found.append(
                f"{name}: {base:.3f} ms -> {current:.3f} ms "
                f"(+{(current / base - 1) * 100:.0f}%, limit {tolerance * 100:.0f}%)"
            )
    return found


def main() -> int:
    """Measure, or compare two measurements.

    Returns:
        A process exit status: 1 when ``check`` finds a regression.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("measure")
    run.add_argument("-o", "--output", type=Path, required=True)
    on_device = commands.add_parser("device")
    on_device.add_argument("-o", "--output", type=Path, required=True)
    on_device.add_argument("--device", help="ADB serial number")
    compare = commands.add_parser("check")
    compare.add_argument("before", type=Path)
    compare.add_argument("after", type=Path)
    compare.add_argument(
        "--floor-ms",
        type=float,
        default=FLOOR_MS,
        help="growth this small is noise; a device's frames are 8 to 17 ms apart",
    )
    args = parser.parse_args()
    if args.command in {"measure", "device"}:
        result = (
            measure()
            if args.command == "measure"
            else measure_device(device=args.device)
        )
        args.output.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
        print(f"slo.py: {result}")
        return 0
    before = json.loads(args.before.read_text())
    after = json.loads(args.after.read_text())
    found = regressions(before, after, floor_ms=args.floor_ms)
    for line in found:
        print(f"slo.py: regression: {line}", file=sys.stderr)
    if not found:
        print(f"slo.py: within {TOLERANCE * 100:.0f}%: {before} -> {after}")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
