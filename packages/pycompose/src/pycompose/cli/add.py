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
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from pycompose_codegen.derive.app import (
    APP_POLICY,
    AppLibraryError,
    compile_app,
    layered_closure,
)
from pycompose_codegen.derive.gradle import extract, resolve
from pycompose_codegen.derive.lock import Report, dumps
from pycompose_codegen.derive.samples import sample
from pycompose_codegen.emit.app_slice import APP_LOCK
from pycompose_codegen.emit.rules import SCHEMA_PATH

from pycompose.cli.https import open_https
from pycompose.cli.project import Project, ProjectError
from pycompose.cli.render import render
from pycompose.cli.validate import validate_file
from pycompose.contract.catalog import REGISTRY
from pycompose.errors import IrValidationError

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
            libraries, closure, bytecode = _fitting(
                android, default, others, group, artifact, versions
            )
            (android / "compose-closure.json").write_text(
                json.dumps(closure, indent=2) + "\n", encoding="utf-8"
            )
            extract(android, f"-PpycomposeCatalog={SCHEMA_PATH}")
            policy = _read(project.root / APP_POLICY).get("components", {})
            lock, report = compile_app(
                android / "build/compose-api", android, library, policy
            )
        if report.errors:
            raise ProjectError(
                "the compiler refused the run", errors="; ".join(report.errors)
            )
        previous = (
            lock_path.read_text(encoding="utf-8") if lock_path.is_file() else None
        )
        # Class-file major 61 is Java 17; a JVM render needs at least the newest.
        lock["jvm"] = max(17, bytecode - 44)
        lock_path.write_text(dumps({"libraries": libraries, **lock}), encoding="utf-8")
        gated = False
        try:
            refused = render_gate(project, lock["components"])
            gated = True
        finally:
            if not gated:
                # Rendering itself failed: the lock goes back to what it was.
                _restore(lock_path, previous)
        for name, reason in refused.items():
            del lock["components"][name]
            report.refused[name] = reason
            report.promoted = [n for n in report.promoted if n != name]
        lock_path.write_text(dumps({"libraries": libraries, **lock}), encoding="utf-8")
        written = True
    finally:
        if not written:
            # A run that wrote no lock leaves the classpath as the lock says.
            _write_libraries(android, current.get("libraries", []))
    return report


def render_gate(project: Project, components: dict[str, Any]) -> dict[str, str]:
    """Render one sample per app component, as the library's gate renders its own.

    Args:
        project: The app, whose lock slice already holds ``components``.
        components: The app's own components.

    Returns:
        The components to refuse, with why: no sample its types can build, a
        sample the validator refuses, or a render the renderer reported on.
    """
    if not components:
        return {}
    REGISTRY.extend(components)
    library = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    catalog = {**library, "components": {**library["components"], **components}}
    refused: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="pycompose-samples-") as scratch:
        directory = Path(scratch)
        snapshots = []
        for name in sorted(components):
            path = directory / f"{name}.json"
            try:
                path.write_text(json.dumps(sample(catalog, name)), encoding="utf-8")
                validate_file(path, wire=False)
            except ValueError as exc:
                refused[name] = f"it has no sample: {exc}"
                continue
            except (ProjectError, IrValidationError) as exc:
                refused[name] = f"its sample does not validate: {exc}"
                continue
            snapshots.append(path)
        out = directory / "rendered"
        if snapshots:
            render(project, snapshots, out)
        for path in snapshots:
            dump = json.loads((out / f"{path.stem}.semantics.json").read_text("utf-8"))
            if dump["reports"]:
                refused[path.stem] = "renders with a report: " + "; ".join(
                    dump["reports"]
                )
    return refused


def _restore(path: Path, previous: str | None) -> None:
    if previous is None:
        path.unlink(missing_ok=True)
    else:
        path.write_text(previous, encoding="utf-8")


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
) -> tuple[list[str], dict[str, Any], int]:
    """The first version whose resolution leaves every BOM-pinned module alone."""
    refusals = []
    for version in versions:
        libraries = sorted([*others, f"{group}:{artifact}:{version}"])
        _write_libraries(android, libraries)
        resolved = resolve(android)
        own = {library.split(":")[0] for library in libraries}
        resolved["artifacts"] = [
            found
            for found in resolved["artifacts"]
            if found["coordinate"].split(":")[0] in own
        ]
        try:
            return libraries, layered_closure(default, resolved), resolved["bytecode"]
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
            with open_https(f"{repository}/{path}", timeout=30) as response:
                metadata = ElementTree.fromstring(response.read())
        except (OSError, ElementTree.ParseError, DefusedXmlException):
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
        shutil.copyfile(assets / "compose-closure.json", closure)
        default = json.loads(closure.read_text(encoding="utf-8"))
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
