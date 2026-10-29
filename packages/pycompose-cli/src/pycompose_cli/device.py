"""ADB discovery and device selection shared by the commands that deploy."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from pycompose_cli.project import ProjectError


def adb() -> str:
    """Locate adb through the SDK or PATH.

    Returns:
        Path to the adb executable.

    Raises:
        ProjectError: If platform-tools is not installed or not on PATH.
    """
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    candidate = (
        Path(sdk).expanduser()
        / "platform-tools"
        / ("adb.exe" if os.name == "nt" else "adb")
        if sdk
        else None
    )
    executable = (
        str(candidate) if candidate and candidate.is_file() else shutil.which("adb")
    )
    if not executable:
        raise ProjectError(
            "adb missing; install SDK platform-tools and set ANDROID_HOME or PATH"
        )
    return executable


def adb_command(executable: str, *args: str) -> str:
    """Run one adb command and return its stdout.

    Args:
        executable: Path to the adb executable.
        *args: adb subcommand and its arguments.

    Returns:
        The command's standard output.

    Raises:
        ProjectError: If adb exits nonzero.
    """
    result = subprocess.run(
        [executable, *args],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=60,
        check=False,
    )
    if result.returncode:
        raise ProjectError(
            "ADB command failed",
            command=args[:4],
            reason=(result.stderr or result.stdout).strip(),
        )
    return result.stdout


def select_device(executable: str, requested: str | None) -> str:
    """Pick one ready device, honoring ``--device`` and ANDROID_SERIAL.

    Args:
        executable: Path to the adb executable.
        requested: Serial from ``--device``, or None for automatic selection.

    Returns:
        The serial number of the selected device.

    Raises:
        ProjectError: If the selected device is unavailable or the ready
            device count is not one.
    """
    lines = adb_command(executable, "devices").splitlines()
    devices = {
        parts[0]: parts[1]
        for line in lines
        if len(parts := line.split()) == 2
        and parts[1] in {"device", "offline", "unauthorized"}
    }
    serial = requested or os.environ.get("ANDROID_SERIAL")
    if serial:
        if devices.get(serial) != "device":
            raise ProjectError(
                "selected device is unavailable or unauthorized", device=serial
            )
        return serial
    ready = [serial for serial, status in devices.items() if status == "device"]
    if len(ready) != 1:
        raise ProjectError(
            "connect one authorized device or select it with --device", devices=devices
        )
    return ready[0]
