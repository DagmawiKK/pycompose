"""``pycompose render``: screenshots and semantics, with no device.

The app's own generated host draws each snapshot on the JVM under Robolectric
-- the same adapters a phone runs -- and writes a PNG and a semantics dump:
the roles, texts, descriptions, actions and bounds accessibility services and
tests read. With no snapshot named, it renders the app's first screen, composed
exactly as ``check`` composes it. ``AppDriver.render`` renders whatever screen a
test has walked to.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from pycompose.host.bridge.imports import fresh_imports
from pycompose.state.disk.documents import documents_at
from pycompose_cli.commands.build import prepare
from pycompose_cli.console import step
from pycompose_cli.project import Project, ProjectError, project_path

TEST = "com.pycompose.host.RenderSnapshots"


def render(project: Project, snapshots: list[Path], out: Path) -> list[Path]:
    """Render snapshots to PNGs and semantics dumps in ``out``.

    Args:
        project: The app.
        snapshots: Snapshot JSON files; none renders the app's first screen.
        out: Where the results go, named after each snapshot.

    Returns:
        The PNG files written; a snapshot that failed to render has its report
        in its semantics dump and no image.

    Raises:
        ProjectError: If rendering failed or wrote no result.
    """
    out = out.resolve()
    with tempfile.TemporaryDirectory(prefix="pycompose-render-") as scratch:
        directory = Path(scratch)
        if not snapshots:
            screen = directory / "screen.json"
            screen.write_text(first_screen(project), encoding="utf-8")
            snapshots = [screen]
        request = directory / "request.json"
        request.write_text(
            json.dumps(
                {
                    "out": str(out),
                    "snapshots": [
                        {"name": path.stem, "path": str(path.resolve())}
                        for path in snapshots
                    ],
                }
            ),
            encoding="utf-8",
        )
        wrapper, env = prepare(project)
        step(f"rendering {len(snapshots)} snapshots on the JVM")
        result = subprocess.run(
            [
                str(wrapper),
                ":host:testDebugUnitTest",
                "--tests",
                TEST,
                f"-PpycomposeRender={request}",
                "--console=plain",
            ],
            cwd=project.android_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    if result.returncode != 0:
        raise ProjectError("rendering failed", output=result.stdout[-3000:])
    dumps = [out / f"{path.stem}.semantics.json" for path in snapshots]
    missing = [path.name for path in dumps if not path.is_file()]
    if missing:
        raise ProjectError("rendering wrote no result", missing=", ".join(missing))
    # A sample that threw has its report and no image.
    images = [out / f"{path.stem}.png" for path in snapshots]
    return [image for image in images if image.is_file()]


def first_screen(project: Project) -> str:
    """The app's first snapshot, composed as its device session composes it.

    Args:
        project: The app.

    Returns:
        The snapshot's JSON.

    Raises:
        ProjectError: If the app published no snapshot.
    """
    from pycompose.host.bridge.session import compose_once

    python = project.table("python")
    source = project_path(project.root, str(python.get("source_dir", "app")))
    with (
        tempfile.TemporaryDirectory() as files,
        documents_at(files),
        fresh_imports(source),
    ):
        snapshot, error = compose_once(str(python.get("entrypoint", "main:app")))
    if not snapshot:
        raise ProjectError("the app published no snapshot", error=error)
    return snapshot
