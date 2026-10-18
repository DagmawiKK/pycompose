"""Debug build/install/launch lifecycle; the host consumes dev bundles later."""

from __future__ import annotations

import re
import subprocess
import threading
from contextlib import suppress

from pycompose.cli.build import build_project
from pycompose.cli.console import notice, ok
from pycompose.cli.dev_server import DevServer
from pycompose.cli.device import adb, adb_command, select_device
from pycompose.cli.project import Project, ProjectError


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
    executable = adb()
    serial = select_device(executable, device)
    artifacts = build_project(project)
    if len(artifacts) != 1:
        raise ProjectError("run requires a single universal debug APK")
    with DevServer(project, port=port) as server:
        tunnel = f"tcp:{server.url.rpartition(':')[2]}"
        reversed_port = False
        try:
            adb_command(executable, "-s", serial, "install", "-r", str(artifacts[0]))
            ok(f"Installed {app_id} on {serial}")
            adb_command(
                executable, "-s", serial, "reverse", "--no-rebind", tunnel, tunnel
            )
            reversed_port = True
            adb_command(
                executable,
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
            notice("Watching Python and resources. Drawables/fonts require a rebuild.")
            notice("Native hot reload and the overlay require debug host integration.")
            threading.Event().wait()
        finally:
            if reversed_port:
                with suppress(ProjectError, OSError, subprocess.TimeoutExpired):
                    adb_command(executable, "-s", serial, "reverse", "--remove", tunnel)
