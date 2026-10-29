"""Measure an app's passes on a device: keystrokes in, time by stage out.

A debug host logs one line per pass under ``PyCompose.pass`` when the frame
showing it is drawn (``PassTiming.kt``): the queue, the Python pass and its
phases, the pull, the host's apply and the frame. ``pycompose bench`` types
into the field focused in the running app, reads those lines back and reports
each stage's median, 95th percentile and worst case. The numbers are the
device's own: an emulator's are not a phone's.
"""

from __future__ import annotations

import json
import time

from pycompose_cli.device import adb, adb_command, select_device
from pycompose_cli.project import ProjectError

TAG = "PyCompose.pass"
"""The logcat tag the host writes each pass's line under."""

KEYCODE_A = "29"
"""What is typed: one letter, so every keystroke is an edit."""

SETTLE = 1.0
"""Seconds for the last keystroke's frame to be drawn and logged."""


def bench(
    *, device: str | None = None, keys: int = 30, interval: float = 0.15
) -> tuple[int, dict[str, dict[str, float]]]:
    """Type ``keys`` letters into the focused field and summarize the passes.

    Args:
        device: ADB serial; automatic selection requires one ready device.
        keys: Keystrokes to send.
        interval: Seconds between keystrokes, after each one is delivered.

    Returns:
        The number of passes logged, and each stage's summary in milliseconds.

    Raises:
        ProjectError: If no pass was logged.
    """
    executable = adb()
    serial = select_device(executable, device)
    adb_command(executable, "-s", serial, "logcat", "-c")
    for _ in range(keys):
        adb_command(executable, "-s", serial, "shell", "input", "keyevent", KEYCODE_A)
        time.sleep(interval)
    time.sleep(SETTLE)
    log = adb_command(
        executable, "-s", serial, "logcat", "-d", "-v", "raw", "-s", f"{TAG}:I"
    )
    passes = [json.loads(line) for line in log.splitlines() if line.startswith("{")]
    if not passes:
        raise ProjectError(
            "no pass was logged: run a debug build (pycompose run) and focus a "
            "text field before benchmarking"
        )
    return len(passes), summarize(passes)


def summarize(passes: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    """Each stage's median, 95th percentile and worst case.

    Args:
        passes: One logged line per pass, milliseconds by stage.

    Returns:
        Per stage, in the order first logged: ``p50``, ``p95`` and ``max``.
    """
    stages = dict.fromkeys(k for p in passes for k in p if k != "commands")
    summary = {}
    for stage in stages:
        values = sorted(p[stage] for p in passes if stage in p)
        summary[stage] = {
            "p50": values[(len(values) - 1) // 2],
            "p95": values[min(len(values) - 1, round(0.95 * (len(values) - 1)))],
            "max": values[-1],
        }
    return summary
