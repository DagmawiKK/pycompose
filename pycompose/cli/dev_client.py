"""The dev client: one prebuilt host that runs any app its dev server serves (§18.8).

Building an app's APK needs Gradle and the Android SDK; running an app on the
dev client needs neither once the client exists. ``pycompose dev-client``
builds it once per PyCompose version -- a generic debug host carrying the
library's whole catalog -- and ``pycompose run --dev-client`` installs it and
serves the app to it over the dev server. A component the client lacks, such
as one from the app's own libraries, renders its declared fallback.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from pycompose.cli.build import build_project
from pycompose.cli.config import change
from pycompose.cli.init import init_project
from pycompose.cli.project import load_project
from pycompose.cli.toolchain import HOME
from pycompose.ir.generated_validators import REGISTRY
from pycompose.version import __version__

APPLICATION_ID = "com.pycompose.devclient"
"""The client's own identity, so it installs beside the apps it runs."""


def dev_client(*, rebuild: bool = False) -> Path:
    """The dev client for this PyCompose version, built once and kept.

    Args:
        rebuild: Build it again even if it exists.

    Returns:
        The client's APK.
    """
    base = HOME.parent / "dev-client" / __version__
    apk = base / "dev-client.apk"
    if apk.is_file() and not rebuild:
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
    return apk
