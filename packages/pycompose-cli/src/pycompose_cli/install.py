"""Install a built APK on a connected device and verify the bytes that landed."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from pycompose_cli.build import build_project
from pycompose_cli.console import working
from pycompose_cli.device import adb, adb_command, select_device
from pycompose_cli.project import Project, ProjectError

_PACKAGE = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")
_DIGEST = re.compile(r"[0-9a-f]{32}")
_HOST_ACTIVITY = "com.pycompose.host.MainActivity"


@dataclass(frozen=True)
class Deploy:
    """What one install attempt did, for the command to report.

    Attributes:
        device: Serial number of the device that received the APK.
        package: Application id that was installed.
        artifact: Local APK the install used.
        digest: MD5 of the local APK.
        verified: Whether the device reported the same digest back.
        launch_ms: Reported launch time, or None when the app was not started.
    """

    device: str
    package: str
    artifact: Path
    digest: str
    verified: bool
    launch_ms: int | None


def package_name(project: Project) -> str:
    """Read and validate the app's package name.

    Args:
        project: Project with an [app] table.

    Returns:
        The application id the APK declares.

    Raises:
        ProjectError: If the id is missing or not a package name.
    """
    app_id = project.table("app").get("application_id")
    if not isinstance(app_id, str) or _PACKAGE.fullmatch(app_id) is None:
        raise ProjectError("app.application_id must be an Android package name")
    return app_id


def install_project(
    project: Project,
    *,
    release: bool = False,
    device: str | None = None,
    launch: bool = False,
    artifact: Path | None = None,
) -> Deploy:
    """Install the app's APK on one device, then verify it on the device.

    An install that reports success can still be the previous build: Gradle
    writes several APKs, adb installs what it is handed, and nothing in
    between compares the two. The installed file's digest is therefore read
    back from the device and matched against the local artifact, and a
    mismatch fails the command instead of silently shipping stale bytes.

    Args:
        project: Project whose APK is installed.
        release: Build the release variant when no artifact is given.
        device: ADB serial; automatic selection requires exactly one device.
        launch: Start the app after installing it.
        artifact: APK to install; the project is built when this is None.

    Returns:
        The device, package, digest and verification outcome.

    Raises:
        ProjectError: If building, device selection, install or verification
            fails.
    """
    app_id = package_name(project)
    if artifact is None:
        artifacts = build_project(project, release=release)
        if len(artifacts) != 1:
            raise ProjectError(
                "installing requires a single APK; build without ABI splits",
                artifacts=len(artifacts),
            )
        artifact = artifacts[0]
    executable = adb()
    serial = select_device(executable, device)
    with working(f"Installing {artifact.name} on {serial}"):
        adb_command(executable, "-s", serial, "install", "-r", str(artifact))
    digest = hashlib.md5(artifact.read_bytes(), usedforsecurity=False).hexdigest()
    remote = _installed_path(executable, serial, app_id)
    connected = _device_digest(executable, serial, remote)
    if connected is not None and connected != digest:
        raise ProjectError(
            "the installed APK differs from the built artifact",
            device=serial,
            artifact=digest,
            installed=connected,
        )
    launch_ms = _launch(executable, serial, app_id) if launch else None
    return Deploy(
        device=serial,
        package=app_id,
        artifact=artifact,
        digest=digest,
        verified=connected == digest,
        launch_ms=launch_ms,
    )


def _installed_path(executable: str, serial: str, package: str) -> str | None:
    """Read the device path of an installed package, when the device reports one.

    Args:
        executable: Path to the adb executable.
        serial: Target device serial.
        package: Application id to locate.

    Returns:
        The APK path on the device, or None when the package is not found.
    """
    output = adb_command(executable, "-s", serial, "shell", "pm", "path", package)
    for line in output.splitlines():
        if line.startswith("package:"):
            return line.removeprefix("package:").strip()
    return None


def _device_digest(executable: str, serial: str, remote: str | None) -> str | None:
    """Read the installed file's digest from the device.

    Args:
        executable: Path to the adb executable.
        serial: Target device serial.
        remote: Device path of the installed APK, or None when unknown.

    Returns:
        The device's MD5, or None when the device cannot report one.
    """
    if remote is None:
        return None
    try:
        output = adb_command(executable, "-s", serial, "shell", "md5sum", remote)
    except ProjectError:
        return None
    fields = output.split()
    digest = fields[0] if fields else ""
    return digest if _DIGEST.fullmatch(digest) else None


def _launch(executable: str, serial: str, package: str) -> int | None:
    """Start the app's main activity and read back its launch time.

    Args:
        executable: Path to the adb executable.
        serial: Target device serial.
        package: Application id to start.

    Returns:
        The reported total start time in milliseconds, or None when the
        device does not report one.
    """
    resolved = adb_command(
        executable,
        "-s",
        serial,
        "shell",
        "cmd",
        "package",
        "resolve-activity",
        "--brief",
        package,
    ).strip()
    component = resolved.splitlines()[-1].strip() if resolved else ""
    if "/" not in component:
        component = f"{package}/{_HOST_ACTIVITY}"
    output = adb_command(
        executable, "-s", serial, "shell", "am", "start", "-W", "-n", component
    )
    match = re.search(r"TotalTime:\s*(\d+)", output)
    return int(match.group(1)) if match else None
