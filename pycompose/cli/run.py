"""Debug build/install/launch lifecycle; the host consumes dev bundles later."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from contextlib import suppress
from pathlib import Path

from pycompose.cli.build import build_project
from pycompose.cli.dev_server import DevServer
from pycompose.cli.project import Project, ProjectError


def _adb() -> str:
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


def _command(adb: str, *args: str) -> str:
    result = subprocess.run(
        [adb, *args],
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


def _device(adb: str, requested: str | None) -> str:
    lines = _command(adb, "devices").splitlines()
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


def run_project(project: Project, *, device: str | None = None, port: int = 0) -> None:
    """Build a debug APK, install and launch it, and serve until interrupted.

    Args:
        project: Project containing the Android scaffold and app configuration.
        device: ADB serial; automatic selection requires exactly one ready device.
        port: Desktop loopback dev-server port; zero selects an available port.

    Raises:
        ProjectError: If app configuration, device selection or deployment fails.
    """
    app_id = project.table("app").get("application_id")
    if (
        not isinstance(app_id, str)
        or re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+", app_id) is None
    ):
        raise ProjectError("app.application_id must be an Android package name")
    adb = _adb()
    serial = _device(adb, device)
    artifacts = build_project(project)
    if len(artifacts) != 1:
        raise ProjectError("run requires a single universal debug APK")
    with DevServer(project, port=port) as server:
        tunnel = f"tcp:{server.url.rpartition(':')[2]}"
        reversed_port = False
        try:
            _command(adb, "-s", serial, "install", "-r", str(artifacts[0]))
            _command(adb, "-s", serial, "reverse", "--no-rebind", tunnel, tunnel)
            reversed_port = True
            _command(
                adb,
                "-s",
                serial,
                "shell",
                "am",
                "start",
                "-W",
                "-n",
                f"{app_id}/com.pycompose.host.MainActivity",
                "--es",
                "pycompose.dev.url",
                server.url,
                "--es",
                "pycompose.dev.token",
                server.token,
            )
            print(
                "Watching Python and resources. Drawables/fonts require a rebuild.",
                flush=True,
            )
            print(
                "Native hot reload and the overlay require debug host integration.",
                flush=True,
            )
            threading.Event().wait()
        finally:
            if reversed_port:
                with suppress(ProjectError, OSError, subprocess.TimeoutExpired):
                    _command(adb, "-s", serial, "reverse", "--remove", tunnel)
