"""Run the extraction tasks in an Android project: the library's or an app's."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from pycompose.errors import PyComposeError


class GradleError(PyComposeError):
    """An extraction task failed."""


def gradle(android: Path, *arguments: str) -> None:
    """Run the project's Gradle wrapper quietly, failing with its error output.

    Args:
        android: The Android project.
        *arguments: Tasks and properties.

    Raises:
        GradleError: If the wrapper exits non-zero.
    """
    result = subprocess.run(
        [str((android / "gradlew").resolve()), "-q", *arguments],
        cwd=android,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GradleError(
            "Gradle failed", tasks=" ".join(arguments), output=result.stderr[-2000:]
        )


def resolve(android: Path) -> dict[str, Any]:
    """Resolve the closure's and the app's groups against the pinned BOM.

    Args:
        android: The Android project, holding ``compose-closure.json``.

    Returns:
        ``resolveCompose``'s report: the BOM, each group's resolved artifacts
        with digests, each tooling module at the BOM's version, and every
        module the BOM pins that something moved.
    """
    gradle(android, ":compose-extract:resolveCompose")
    report: dict[str, Any] = json.loads(
        (android / "build/compose-api/resolved.json").read_text(encoding="utf-8")
    )
    return report


def extract(android: Path, *properties: str) -> None:
    """Extract the pinned API and its source defaults as evidence.

    Args:
        android: The Android project.
        *properties: Gradle properties, such as an app's ``-PpycomposeCatalog``.
    """
    gradle(
        android,
        ":compose-extract:dumpComposeApi",
        ":compose-extract:dumpComposeDefaults",
        *properties,
    )
