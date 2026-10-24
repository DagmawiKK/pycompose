"""The pinned toolchain, and ``pycompose setup`` to install it (plan 31 §21.5).

An app never chooses Gradle, AGP, Kotlin, the Compose BOM or SDK levels: the
Android template pins them, and ``templates/toolchain.toml`` pins the JDK and
the Android command-line tools beside them. ``pycompose setup`` installs those
into a PyCompose-managed directory, verifying every archive against its
digest, and installs the SDK packages through ``sdkmanager``. The SDK licences
are shown in the terminal for the person to accept; setup never accepts them.
"""

from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tomllib
import urllib.request
import zipfile
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from pycompose.cli.project import ProjectError

HOME = Path(os.environ.get("PYCOMPOSE_HOME", "~/.pycompose")).expanduser() / "toolchain"
"""Where ``setup`` installs; ``PYCOMPOSE_HOME`` moves it."""


@dataclass(frozen=True)
class Toolchain:
    """One release's tested combination.

    Attributes:
        gradle: Gradle's version, from the wrapper.
        gradle_sha256: The wrapper's distribution checksum.
        agp: The Android Gradle plugin.
        kotlin: Kotlin.
        compose_bom: The Compose BOM.
        compile_sdk: The SDK the host compiles against.
        target_sdk: The SDK the host targets.
        min_sdk: The oldest Android the host runs on.
        locked: What ``setup`` installs: ``templates/toolchain.toml``.
    """

    gradle: str
    gradle_sha256: str
    agp: str
    kotlin: str
    compose_bom: str
    compile_sdk: int
    target_sdk: int
    min_sdk: int
    locked: dict[str, Any]


def lock() -> Toolchain:
    """Read the release's toolchain from the template and the lock.

    Returns:
        The toolchain.
    """
    templates = files("pycompose").joinpath("templates")
    android = templates.joinpath("android")
    wrapper = android.joinpath("gradle/wrapper/gradle-wrapper.properties").read_text(
        "utf-8"
    )
    versions = tomllib.loads(
        android.joinpath("gradle/libs.versions.toml").read_text("utf-8")
    )["versions"]
    host = android.joinpath("host/build.gradle.kts").read_text("utf-8")

    def sdk(name: str) -> int:
        match = re.search(rf"\b{name} = (\d+)", host)
        assert match is not None, name
        return int(match.group(1))

    gradle = re.search(r"gradle-([\d.]+)-bin\.zip", wrapper)
    checksum = re.search(r"distributionSha256Sum=(\w+)", wrapper)
    assert gradle is not None and checksum is not None
    return Toolchain(
        gradle=gradle.group(1),
        gradle_sha256=checksum.group(1),
        agp=versions["agp"],
        kotlin=versions["kotlin"],
        compose_bom=versions["compose-bom"],
        compile_sdk=sdk("compileSdk"),
        target_sdk=sdk("targetSdk"),
        min_sdk=sdk("minSdk"),
        locked=tomllib.loads(templates.joinpath("toolchain.toml").read_text("utf-8")),
    )


def sdk_root() -> str | None:
    """The managed Android SDK, once ``setup`` has installed it.

    Returns:
        Its path, or None.
    """
    root = HOME / "android-sdk"
    return str(root) if (root / "platform-tools").is_dir() else None


STUDIO_SDKS = (
    "~/Library/Android/sdk",
    "~/Android/Sdk",
    "%LOCALAPPDATA%/Android/Sdk",
)
"""Where Android Studio installs the SDK on macOS, Linux and Windows."""


def android_sdk() -> Path | None:
    """The SDK a build uses: the managed one, ``ANDROID_HOME``, then Android Studio's.

    Returns:
        Its path, or None when there is none to use.
    """
    configured = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    candidates = [sdk_root(), configured, *(os.path.expandvars(p) for p in STUDIO_SDKS)]
    for candidate in candidates:
        if candidate and (path := Path(candidate).expanduser()).is_dir():
            return path
    return None


def jdk_home() -> str | None:
    """The managed JDK, once ``setup`` has installed it.

    Returns:
        Its home, or None.
    """
    root = HOME / "jdk"
    for home in (root, root / "Contents/Home"):
        if (home / "bin" / ("java.exe" if os.name == "nt" else "java")).is_file():
            return str(home)
    return None


def host() -> str:
    """The lock's name for this machine, such as ``mac-aarch64``.

    Returns:
        The platform key.

    Raises:
        ProjectError: If the toolchain has no build for this machine.
    """
    system = {"Darwin": "mac", "Linux": "linux", "Windows": "windows"}.get(
        platform.system()
    )
    machine = {
        "arm64": "aarch64",
        "aarch64": "aarch64",
        "x86_64": "x64",
        "AMD64": "x64",
    }.get(platform.machine())
    if system is None or machine is None:
        raise ProjectError(
            "no pinned toolchain for this machine", machine=platform.platform()
        )
    return f"{system}-{machine}"


def setup() -> None:
    """Install the pinned JDK, command-line tools and SDK packages.

    Raises:
        ProjectError: If a download fails its digest or ``sdkmanager`` fails.
    """
    toolchain = lock()
    key = host()
    locked = toolchain.locked
    if jdk_home() is None:
        archive = locked["jdk"]["archives"][key]
        _install(archive["url"], "sha256", archive["sha256"], HOME / "jdk")
    tools = HOME / "android-sdk/cmdline-tools/latest"
    if not tools.is_dir():
        archive = locked["android"]["archives"][key]
        _install(archive["url"], "sha1", archive["sha1"], tools)
    abi = "arm64-v8a" if key.endswith("aarch64") else "x86_64"
    android = locked["android"]
    packages = [
        "platform-tools",
        f"platforms;{android['platform']}",
        f"build-tools;{android['build_tools']}",
        "emulator",
        f"system-images;{android['system_image']};{abi}",
    ]
    manager = tools / "bin" / ("sdkmanager.bat" if os.name == "nt" else "sdkmanager")
    env = {**os.environ, "JAVA_HOME": jdk_home() or ""}
    root = f"--sdk_root={HOME / 'android-sdk'}"
    # The licences are the person's to accept: sdkmanager asks in this terminal.
    for command in (
        [str(manager), root, "--licenses"],
        [str(manager), root, *packages],
    ):
        if subprocess.run(command, env=env, check=False).returncode != 0:
            raise ProjectError("sdkmanager failed", command=" ".join(command[2:]))


def _install(url: str, algorithm: str, digest: str, target: Path) -> None:
    """Download one archive, verify it, and unpack its single top directory."""
    download = target.with_name(target.name + ".download")
    download.parent.mkdir(parents=True, exist_ok=True)
    with (
        urllib.request.urlopen(url, timeout=600) as response,
        download.open("wb") as out,
    ):
        shutil.copyfileobj(response, out)
    actual = hashlib.new(algorithm, download.read_bytes()).hexdigest()
    if actual != digest:
        download.unlink()
        raise ProjectError(
            "downloaded archive does not match its pinned digest", url=url
        )
    unpack(download, target)
    download.unlink()


def unpack(archive: Path, target: Path) -> None:
    """Unpack an archive's single top-level directory as ``target``.

    A member that would land outside ``target`` is refused before anything is
    extracted.

    Args:
        archive: A ``.zip`` or ``.tar.gz``.
        target: Where its contents go.
    """
    staging = target.with_name(target.name + ".staging")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            _confined(staging, names)
            bundle.extractall(staging)
            for info in bundle.infolist():
                mode = info.external_attr >> 16
                if mode & 0o111:
                    (staging / info.filename).chmod(mode & 0o777)
    else:
        with tarfile.open(archive) as bundle:
            _confined(staging, bundle.getnames())
            bundle.extractall(staging, filter="data")
    tops = list(staging.iterdir())
    top = tops[0] if len(tops) == 1 and tops[0].is_dir() else staging
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(top), str(target))
    shutil.rmtree(staging, ignore_errors=True)


def _confined(root: Path, names: list[str]) -> None:
    for name in names:
        if not (root / name).resolve().is_relative_to(root.resolve()):
            raise ProjectError("archive member escapes its directory", member=name)
