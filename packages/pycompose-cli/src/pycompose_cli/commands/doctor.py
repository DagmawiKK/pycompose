"""Read-only toolchain diagnostics; plugin versions are explicitly declared."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

from pycompose.errors import PyComposeError
from pycompose.model.catalog.lock import SCHEMA_VERSION
from pycompose.version import __version__
from pycompose_cli.project import check_project_versions, load_project
from pycompose_cli.project.toolchain import android_sdk, jdk_home


@dataclass(frozen=True, slots=True)
class ToolCheck:
    """One observable toolchain fact and whether it meets v1 requirements.

    Attributes:
        name: Tool or compatibility contract.
        detail: Version, path or corrective diagnostic.
        ok: Whether this check passed.
    """

    name: str
    detail: str
    ok: bool


def _probe(executable: str, argument: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [executable, argument],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def _jdk() -> ToolCheck:
    # The JDK pycompose setup installed is the one builds use.
    home = jdk_home() or os.environ.get("JAVA_HOME")
    executable = (
        str(Path(home) / "bin" / ("java.exe" if os.name == "nt" else "java"))
        if home
        else shutil.which("java")
    )
    if not executable:
        return ToolCheck(
            "JDK", "Java missing; install JDK 17+ and set JAVA_HOME", False
        )
    ok, text = _probe(executable, "-version")
    version = re.search(r'version\s+"([0-9]+(?:\.[0-9]+)*)(?:[-+_][^"]*)?"', text)
    if not ok or version is None:
        return ToolCheck(
            "JDK", "Java failed; check JAVA_HOME and install JDK 17+", False
        )
    value = version[1]
    major = int(value.split(".")[1] if value.startswith("1.") else value.split(".")[0])
    return ToolCheck(
        "JDK", value + ("; JDK 17+ required" if major < 17 else ""), major >= 17
    )


def _sdk_path(directory: Path) -> Path | None:
    configured = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if configured:
        return Path(configured).expanduser()
    properties = directory / "local.properties"
    if properties.is_file():
        for line in properties.read_text(encoding="utf-8").splitlines():
            if line.startswith("sdk.dir="):
                path = Path(
                    line.partition("=")[2].replace("\\:", ":").replace("\\\\", "\\")
                ).expanduser()
                return path if path.is_absolute() else directory / path
    return android_sdk()


def _sdk(sdk: Path | None) -> ToolCheck:
    if sdk is None or not sdk.is_dir():
        return ToolCheck(
            "SDK",
            "Android SDK missing; set ANDROID_HOME or sdk.dir in local.properties",
            False,
        )
    platforms = sorted(
        path.parent.name
        for path in (sdk / "platforms").glob("*/android.jar")
        if path.is_file()
    )
    tools = sorted(
        path.parent.name
        for path in (sdk / "build-tools").glob("*/aapt2*")
        if path.name in {"aapt2", "aapt2.exe"}
        and path.is_file()
        and (os.name == "nt" or os.access(path, os.X_OK))
    )
    home, alternate = os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT")
    if (
        home
        and alternate
        and Path(home).expanduser().resolve() != Path(alternate).expanduser().resolve()
    ):
        return ToolCheck("SDK", "ANDROID_HOME and ANDROID_SDK_ROOT disagree", False)
    detail = (
        f"{sdk}; platforms: {', '.join(platforms) or 'missing'}; "
        f"build-tools: {', '.join(tools) or 'missing'}"
    )
    return ToolCheck("SDK", detail, bool(platforms and tools))


def _adb(sdk: Path | None) -> ToolCheck:
    path = (
        sdk / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")
        if sdk
        else None
    )
    executable = str(path) if path and path.is_file() else shutil.which("adb")
    if not executable:
        return ToolCheck(
            "ADB", "adb missing; install Android SDK platform-tools", False
        )
    ok, text = _probe(executable, "version")
    return ToolCheck(
        "ADB",
        text or "adb version probe failed",
        ok and "Android Debug Bridge version" in text,
    )


def _plugins(directory: Path) -> list[ToolCheck]:
    try:
        data = tomllib.loads(
            (directory / "gradle" / "libs.versions.toml").read_text(encoding="utf-8")
        )
        versions = data.get("versions", {})
    except (OSError, ValueError):
        versions = {}
    if not isinstance(versions, dict):
        versions = {}
    result = []
    for key, label in (("agp", "AGP"), ("chaquopy", "Chaquopy")):
        value = versions.get(key)
        ok = (
            isinstance(value, str)
            and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-.][A-Za-z0-9]+)*", value)
            is not None
        )
        if key == "chaquopy" and ok:
            ok = value.split(".")[0] == "17"
        detail = (
            value
            if isinstance(value, str)
            else "missing; declare the version in gradle/libs.versions.toml"
        )
        if key == "chaquopy" and not ok:
            detail += "; Chaquopy 17 is required"
        result.append(ToolCheck(f"{label} (declared)", detail, ok))
    return result


def doctor(directory: Path) -> tuple[ToolCheck, ...]:
    """Probe installed tools and separately report project version declarations.

    Args:
        directory: Project directory; system checks still run without a project.

    Returns:
        SDK, JDK, ADB, wrapper, plugin and schema checks, without network installs.
    """
    native = directory
    try:
        project = load_project(directory)
        native = project.android_root
        schema = check_project_versions(project)
        schema_check = ToolCheck("Schema", f"{schema}; library {__version__}", True)
    except (PyComposeError, OSError) as exc:
        schema_check = ToolCheck(
            "Schema", f"library supports {SCHEMA_VERSION}: {exc}", False
        )
    try:
        sdk = _sdk_path(native)
        sdk_check = _sdk(sdk)
    except (OSError, ValueError) as exc:
        sdk = None
        sdk_check = ToolCheck("SDK", f"cannot read SDK configuration: {exc}", False)
    wrapper = native / ("gradlew.bat" if os.name == "nt" else "gradlew")
    result = [
        sdk_check,
        _jdk(),
        _adb(sdk),
        ToolCheck(
            "Gradle wrapper",
            str(wrapper) if wrapper.is_file() else "missing; Android scaffold required",
            wrapper.is_file() and (os.name == "nt" or os.access(wrapper, os.X_OK)),
        ),
        *_plugins(native),
        schema_check,
    ]
    return tuple(result)
