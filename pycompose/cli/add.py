"""``pycompose add``: wrap a Compose library the app declares (plan 31 §16.3, §19).

The library is resolved against the pinned BOM, extracted into the app's own
Android project exactly as Google's artifacts are extracted for the library,
and compiled by the same rules. Its components join the app's catalog through
the app's lock slice, ``compose.lock.json``, which also records the libraries
the app asked for; ``pycompose build`` puts them on the native classpath from
there. Nothing is wrapped by hand: a component that does not derive is refused
with its reason.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from pycompose.cli.project import Project, ProjectError
from pycompose.compiler.app import (
    APP_POLICY,
    AppLibraryError,
    compile_app,
    layered_closure,
)
from pycompose.compiler.lock import Report, dumps
from pycompose.schema.codegen.app_slice import APP_LOCK
from pycompose.schema.codegen.rules import SCHEMA_PATH

REPOSITORIES = (
    "https://dl.google.com/android/maven2",
    "https://repo1.maven.org/maven2",
)
"""Where a version is looked up when none is given: the app's own repositories."""

CANDIDATES = 5
"""Newest stable versions tried, in order, until one fits the pinned BOM."""

LIBRARIES = "compose-libraries.txt"
"""The coordinates the renderer puts on the classpath, written from the lock."""

_COORDINATE = re.compile(r"[\w.-]+:[\w.-]+(?::[\w.+-]+)?")


def add_library(project: Project, coordinate: str) -> Report:
    """Resolve, extract and compile one library into the app's lock slice.

    Args:
        project: The app.
        coordinate: ``group:artifact`` or ``group:artifact:version``.

    Returns:
        The compiler's report: promoted and refused components, with reasons.

    Raises:
        ProjectError: If the coordinate is malformed, no version fits the
            pinned BOM, extraction fails or the compiler refuses the run.
    """
    if not _COORDINATE.fullmatch(coordinate):
        raise ProjectError("expected group:artifact[:version]", coordinate=coordinate)
    group, artifact, *pinned = coordinate.split(":")
    android = project.android_root
    lock_path = project.root / APP_LOCK
    current = _read(lock_path)
    others = [
        library
        for library in current.get("libraries", [])
        if not library.startswith(f"{group}:{artifact}:")
    ]
    versions = pinned or _published(group, artifact)[:CANDIDATES]
    library = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    written = False
    try:
        with _extractor(android) as default:
            libraries, closure = _fitting(
                android, default, others, group, artifact, versions
            )
            (android / "compose-closure.json").write_text(
                json.dumps(closure, indent=2) + "\n", encoding="utf-8"
            )
            _gradle(
                android,
                ":compose-extract:dumpComposeApi",
                ":compose-extract:dumpComposeDefaults",
                f"-PpycomposeCatalog={SCHEMA_PATH}",
            )
            policy = _read(project.root / APP_POLICY).get("components", {})
            lock, report = compile_app(
                android / "build/compose-api", android, library, policy
            )
        if report.errors:
            raise ProjectError(
                "the compiler refused the run", errors="; ".join(report.errors)
            )
        lock_path.write_text(dumps({"libraries": libraries, **lock}), encoding="utf-8")
        written = True
    finally:
        if not written:
            # A run that wrote no lock leaves the classpath as the lock says.
            _write_libraries(android, current.get("libraries", []))
    return report


def sync_libraries(project: Project) -> None:
    """Put the libraries the app's lock slice records on the native classpath.

    Args:
        project: The app.
    """
    _write_libraries(
        project.android_root, _read(project.root / APP_LOCK).get("libraries", [])
    )


def _fitting(
    android: Path,
    default: dict[str, Any],
    others: list[str],
    group: str,
    artifact: str,
    versions: list[str],
) -> tuple[list[str], dict[str, Any]]:
    """The first version whose resolution leaves every BOM-pinned module alone."""
    refusals = []
    for version in versions:
        libraries = sorted([*others, f"{group}:{artifact}:{version}"])
        _write_libraries(android, libraries)
        _gradle(android, ":compose-extract:resolveComposeLibraries")
        resolved = json.loads(
            (android / "build/compose-api/libraries.json").read_text(encoding="utf-8")
        )
        try:
            return libraries, layered_closure(default, resolved)
        except AppLibraryError as exc:
            refusals.append(f"{version}: {exc}")
    raise ProjectError(
        "no version fits the pinned BOM",
        library=f"{group}:{artifact}",
        tried="; ".join(refusals) or "none published",
    )


def _published(group: str, artifact: str) -> list[str]:
    """Stable published versions, newest first, from the first repository with any."""
    path = f"{group.replace('.', '/')}/{artifact}/maven-metadata.xml"
    for repository in REPOSITORIES:
        try:
            with urllib.request.urlopen(f"{repository}/{path}", timeout=30) as response:
                metadata = ElementTree.fromstring(response.read())
        except OSError:
            continue
        versions = [
            node.text
            for node in metadata.iter("version")
            if node.text and re.fullmatch(r"\d+(\.\d+)*", node.text)
        ]
        if versions:
            return sorted(versions, key=_version_key, reverse=True)
    raise ProjectError("no published versions found", library=f"{group}:{artifact}")


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


@contextmanager
def _extractor(android: Path) -> Iterator[dict[str, Any]]:
    """Lend the app's Android project the extraction module while ``add`` runs.

    Args:
        android: The app's Android project.

    Yields:
        dict[str, Any]: The library's default closure.

    Raises:
        ProjectError: If an earlier extraction left its module behind.
    """
    module = android / "compose-extract"
    closure = android / "compose-closure.json"
    if module.exists() or closure.exists():
        raise ProjectError("an extraction is already in progress", path=android)
    with as_file(files("pycompose").joinpath("templates", "extract")) as assets:
        shutil.copytree(assets / "compose-extract", module)
        default = json.loads(
            (assets / "compose-closure.json").read_text(encoding="utf-8")
        )
    try:
        yield default
    finally:
        shutil.rmtree(module, ignore_errors=True)
        closure.unlink(missing_ok=True)


def _write_libraries(android: Path, libraries: list[str]) -> None:
    target = android / LIBRARIES
    if libraries:
        target.write_text(
            "".join(f"{library}\n" for library in libraries), encoding="utf-8"
        )
    else:
        target.unlink(missing_ok=True)


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ProjectError("expected a JSON object", path=path)
    return data


def _gradle(android: Path, *arguments: str) -> None:
    wrapper = android / "gradlew"
    result = subprocess.run(
        [str(wrapper), "-q", *arguments],
        cwd=android,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ProjectError(
            "Gradle failed", tasks=" ".join(arguments), output=result.stderr[-2000:]
        )
