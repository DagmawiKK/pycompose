"""``pycompose check``: every mistake a build would find, found before it (§18.7).

In about a second and with no device or Gradle: the configuration against its
published schema, each error naming the key and its fix (§21.4); the app
itself, imported and composed exactly as the device's session composes it, so
its first snapshot must validate; and Google Play's policy over the manifest
the build would ship and the pinned toolchain (§21.7).
"""

from __future__ import annotations

import json
import re
import tempfile
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from importlib.resources import files
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element

from defusedxml import ElementTree

from pycompose.bridge.imports import fresh_imports
from pycompose.cli.prebuild import generated, plan
from pycompose.cli.project import Project, ProjectError, load_project, project_path
from pycompose.cli.toolchain import lock
from pycompose.repository import documents_at

PLAY_TARGETS = ((date(2025, 8, 31), 35), (date(2026, 8, 31), 36))
"""The API level new apps and updates must target on Google Play, from each date."""

_ANDROID = "{http://schemas.android.com/apk/res/android}"


@dataclass(frozen=True)
class Problem:
    """One thing a build or the store would refuse.

    Attributes:
        where: The config key, file or policy concerned.
        message: What is wrong.
        fix: What to do about it.
    """

    where: str
    message: str
    fix: str


def check(directory: Path, *, today: date | None = None) -> list[Problem]:
    """Check an app without a device, a build or the network.

    Args:
        directory: The app root, holding ``pycompose.toml``.
        today: The date Play's policy is read against; today by default.

    Returns:
        Every problem found; none means a build should succeed.
    """
    try:
        config = tomllib.loads(
            (directory / "pycompose.toml").read_text(encoding="utf-8")
        )
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return [Problem("pycompose.toml", str(exc), "fix the file's TOML syntax")]
    problems = config_problems(config)
    if problems:
        return problems
    project = load_project(directory)
    try:
        manifest = _manifest(project)
    except ProjectError as exc:
        return [Problem("android", str(exc), "fix the setting the message names")]
    problems += play_problems(manifest, today or date.today())
    problems += app_problems(project)
    return problems


def config_problems(config: dict[str, Any]) -> list[Problem]:
    """Validate a configuration against the published schema.

    Args:
        config: The parsed ``pycompose.toml``.

    Returns:
        One problem per violation, naming the key.
    """
    schema = json.loads(
        files("pycompose")
        .joinpath("schema", "pycompose.schema.json")
        .read_text("utf-8")
    )
    return list(_validate(config, schema, ""))


def _validate(value: Any, schema: dict[str, Any], key: str) -> Iterator[Problem]:
    kind = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "integer": int}
    if kind and not (isinstance(value, types[kind]) and not isinstance(value, bool)):
        article = "an" if kind[0] in "aeiou" else "a"
        yield Problem(
            key or "pycompose.toml", f"must be {article} {kind}", _fix(schema)
        )
    elif kind == "object":
        yield from _object(value, schema, key)
    elif kind == "array":
        for index, item in enumerate(value):
            yield from _validate(item, schema.get("items", {}), f"{key}[{index}]")
    elif kind == "string":
        if len(value) < schema.get("minLength", 0):
            yield Problem(key, "must not be empty", _fix(schema))
        elif "pattern" in schema and re.search(schema["pattern"], value) is None:
            yield Problem(key, f"{value!r} is not valid", _fix(schema))
    elif kind == "integer" and not (
        schema.get("minimum", value) <= value <= schema.get("maximum", value)
    ):
        yield Problem(key, f"{value} is out of range", _fix(schema))


def _object(
    value: dict[str, Any], schema: dict[str, Any], key: str
) -> Iterator[Problem]:
    properties = schema.get("properties", {})
    for name in schema.get("required", []):
        if name not in value:
            yield Problem(
                f"{key}.{name}".lstrip("."),
                "is required",
                _fix(properties.get(name, {})),
            )
    for name, item in value.items():
        path = f"{key}.{name}".lstrip(".")
        if name in properties:
            yield from _validate(item, properties[name], path)
        elif schema.get("additionalProperties") is False:
            yield Problem(
                path,
                "is not a known key",
                f"known keys: {', '.join(sorted(properties))}",
            )


def _fix(schema: dict[str, Any]) -> str:
    return str(schema.get("description", "see the configuration schema"))


def play_problems(manifest: str, today: date) -> list[Problem]:
    """Check what Google Play refuses: target SDK, exports, services, cleartext.

    Args:
        manifest: The manifest the build would ship.
        today: The date the target-SDK deadline is read against.

    Returns:
        One problem per policy the app would break.
    """
    problems = _toolchain_problems(today)
    root = ElementTree.fromstring(manifest)
    application = root.find("application")
    if application is None:
        return problems
    if application.get(f"{_ANDROID}usesCleartextTraffic") == "true":
        problems.append(
            Problem(
                "manifest", "allows cleartext traffic", "remove usesCleartextTraffic"
            )
        )
    requested = {p.get(f"{_ANDROID}name") for p in root.findall("uses-permission")}
    foreground = "android.permission.FOREGROUND_SERVICE" in requested
    for component in application:
        problems += _component_problems(component, foreground=foreground)
    return problems


def _toolchain_problems(today: date) -> list[Problem]:
    toolchain = lock()
    problems = []
    required = max(
        (level for since, level in PLAY_TARGETS if since <= today), default=0
    )
    if toolchain.target_sdk < required:
        problems.append(
            Problem(
                "toolchain target SDK",
                f"targets API {toolchain.target_sdk}; Google Play requires {required}",
                "upgrade PyCompose to a release targeting the required level",
            )
        )
    if tuple(int(p) for p in toolchain.agp.split(".")[:3]) < (8, 5, 1):
        problems.append(
            Problem(
                "toolchain AGP",
                "native libraries are not packaged for 16 KB pages",
                "upgrade PyCompose",
            )
        )
    return problems


def _component_problems(component: Element, *, foreground: bool) -> list[Problem]:
    name = f"{component.tag} {component.get(f'{_ANDROID}name', '')}"
    problems = []
    typed = component.get(f"{_ANDROID}foregroundServiceType") is not None
    if component.tag == "service" and foreground and not typed:
        problems.append(Problem(name, "has no foregroundServiceType", "declare one"))
    exported = component.get(f"{_ANDROID}exported") == "true"
    launcher = any(
        c.get(f"{_ANDROID}name") == "android.intent.category.LAUNCHER"
        for c in component.iter("category")
    )
    guarded = component.get(f"{_ANDROID}permission") is not None
    if exported and not (launcher or guarded):
        problems.append(
            Problem(
                name,
                "is exported without a permission",
                "guard it with android:permission or stop exporting it",
            )
        )
    return problems


def app_problems(project: Project) -> list[Problem]:
    """Compose the app as its device session does, and validate the snapshot.

    Args:
        project: The app.

    Returns:
        The failure, if composing or validating failed.
    """
    from pycompose.bridge.runtime import RuntimeSession

    python = project.table("python")
    source = project_path(project.root, str(python.get("source_dir", "app")))
    entrypoint = str(python.get("entrypoint", "main:app"))
    with (
        tempfile.TemporaryDirectory() as files,
        documents_at(files),
        fresh_imports(source),
    ):
        try:
            session = RuntimeSession(entrypoint, "", debug=True)
            session.close()
        except Exception as exc:  # any failure is the app's to see
            return [
                Problem("app", f"{type(exc).__name__}: {exc}", "fix the app's code")
            ]
    return []


def _manifest(project: Project) -> str:
    if generated(project):
        return plan(project).files["host/src/main/AndroidManifest.xml"].decode()
    source = project_path(project.android_root, "host/src/main/AndroidManifest.xml")
    return source.read_text(encoding="utf-8")
