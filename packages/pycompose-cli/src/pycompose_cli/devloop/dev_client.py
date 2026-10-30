"""The dev client: one prebuilt host that runs any app its dev server serves (§18.8).

Building an app's APK needs Gradle and the Android SDK; running an app on the
dev client needs neither once the client exists. ``pycompose dev-client``
builds it once per PyCompose version -- a generic debug host carrying the
library's whole catalog -- and ``pycompose run --dev-client`` installs it and
serves the app to it over the dev server. A component the client lacks, such
as one from the app's own libraries, renders its declared fallback.

The client bundles the framework it was built from, so a client built before
the framework changed would run the app against the old one; it is refused
with the command that rebuilds it rather than failing on the device.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pycompose
from pycompose.contract.catalog import REGISTRY
from pycompose.version import __version__
from pycompose_cli.commands.build import build_project
from pycompose_cli.commands.config import change
from pycompose_cli.commands.init import init_project
from pycompose_cli.project import ProjectError, load_project
from pycompose_cli.project.toolchain import HOME

APPLICATION_ID = "com.pycompose.devclient"
"""The client's own identity, so it installs beside the apps it runs."""

FINGERPRINT = "framework.sha256"
"""Beside the APK: the fingerprint of the framework it was built from."""


def framework_fingerprint() -> str:
    """Hash the framework a client bundles: the runtime and the host template.

    Returns:
        The hex digest of every file's path and bytes.
    """
    roots = {
        "runtime": Path(pycompose.__file__).parent,
        "template": Path(__file__).resolve().parents[1] / "templates" / "android",
    }
    digest = hashlib.sha256()
    for name, root in roots.items():
        for path in sorted(root.rglob("*")):
            if (
                path.is_file()
                and "__pycache__" not in path.parts
                and path.name != ".DS_Store"
            ):
                relative = f"{name}/{path.relative_to(root).as_posix()}"
                digest.update(relative.encode() + b"\0")
                digest.update(path.read_bytes())
    return digest.hexdigest()


def dev_client(*, rebuild: bool = False) -> Path:
    """The dev client for this PyCompose version, built once and kept.

    Args:
        rebuild: Build it again even if it exists.

    Returns:
        The client's APK.

    Raises:
        ProjectError: The kept client was built from another framework.
    """
    base = HOME.parent / "dev-client" / __version__
    apk = base / "dev-client.apk"
    fingerprint = base / FINGERPRINT
    current = framework_fingerprint()
    if apk.is_file() and not rebuild:
        built = fingerprint.read_text().strip() if fingerprint.is_file() else None
        if built != current:
            raise ProjectError(
                "the dev client was built from a different PyCompose framework; "
                "rebuild it with `pycompose dev-client --rebuild`"
            )
        return apk
    shutil.rmtree(base / "client", ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    root, _, _ = init_project("client", directory=base)
    # An app's slice holds the components it references, so the client
    # references them all: it must render whatever app it is served.
    names = sorted(REGISTRY.components)
    (root / "app/catalog.py").write_text(
        '"""Every component, so the dev client carries the whole catalog."""\n\n'
        "from m3 import (  # noqa: F401\n"
        + "".join(f"    {name},\n" for name in names)
        + ")\n",
        encoding="utf-8",
    )
    project = load_project(root)
    change(project, "application_id", APPLICATION_ID)
    change(load_project(root), "label", "PyCompose Dev")
    (artifact,) = build_project(load_project(root))
    shutil.copyfile(artifact, apk)
    fingerprint.write_text(current + "\n")
    return apk
