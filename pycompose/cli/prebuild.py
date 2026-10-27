"""The Android project is build output, generated from the app (plan 31 §21).

``.pycompose/android/`` is written on every build from the app's inputs --
``pycompose.toml``, ``resources/``, the icon, the theme, its fragments and its
lock slice -- over PyCompose's own template, and never edited or committed. Upgrading
PyCompose regenerates it, so the template version is not the app author's
concern. A project whose Android directory is the app root (``--native``, or an
ejected project) owns its files, and is never regenerated.

Each generated file records where it came from; ``pycompose explain`` prints
it. Fragments are merged, never copied over generated files: a manifest
fragment (``android/manifest.xml``) becomes a library module AGP's manifest
merger folds in, and ``resources/android/res/`` is a raw resource overlay.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from pycompose.cli.icons import icon_files
from pycompose.cli.permissions import selected_permissions, with_permissions
from pycompose.cli.plugins import AndroidModel, manifest_with, run_plugins
from pycompose.cli.project import Project, ProjectError, project_path
from pycompose.cli.resources import resource_files
from pycompose.cli.theme import theme_files
from pycompose.schema.codegen.app_slice import APP_LOCK

GENERATED = ".pycompose/android"
"""Where a generated project lives, relative to the app root."""

RECORD = ".pycompose/prebuild.json"
"""Inside the generated project: every file the last run wrote, and its sources."""

_TEMPLATE_ONLY = frozenset({"app", "resources", "template.toml"})
_MANIFEST = "host/src/main/AndroidManifest.xml"
_FRAGMENT = "android/manifest.xml"
_OVERLAY = "resources/android/res"


@dataclass
class Generation:
    """The project to write: each file's bytes and what produced it."""

    files: dict[str, bytes] = field(default_factory=dict)
    sources: dict[str, list[str]] = field(default_factory=dict)

    def add(self, path: str, content: bytes, source: str) -> None:
        self.files[path] = content
        self.sources[path] = [source]


def generated(project: Project) -> bool:
    """Report whether the app's Android project is generated, not owned.

    Args:
        project: The app.

    Returns:
        True when it lives in ``.pycompose/android``.
    """
    return project.table("toolchain").get("android_dir", ".") == GENERATED


def plan(project: Project) -> Generation:
    """Compute the whole generated project without writing anything.

    A fragment that would replace a generated file is refused.

    Args:
        project: The app.

    Returns:
        Every file, by path relative to the Android project.
    """
    generation = Generation()
    version = _template_version(files("pycompose").joinpath("templates", "android"))
    for path, content in template_files():
        generation.add(path, content, f"template {version}")
    prefix = project.android_root.relative_to(project.root).as_posix() + "/"
    for name, content in resource_files(project).items():
        generation.add(name.removeprefix(prefix), content, "resources/")
    for name, content in icon_files(project).items():
        generation.add(name, content, "[app] icon")
    for name, content in theme_files(project).items():
        generation.add(name, content, "[theme]")
    chosen = selected_permissions(project)
    manifest = generation.files[_MANIFEST].decode()
    merged = with_permissions(manifest, chosen)
    if merged != manifest:
        generation.files[_MANIFEST] = merged.encode()
        generation.sources[_MANIFEST].append("[android] permissions")
    _libraries(project, generation)
    _fragments(project, generation)
    _plugins(project, generation)
    return generation


def prebuild(project: Project) -> list[str]:
    """Write the generated project, changing only what differs.

    Args:
        project: The app.

    Only files the generation owns are written or removed: build outputs,
    caches and ``local.properties`` are left as they are.

    Returns:
        The paths written or removed, relative to the Android project.

    Raises:
        ProjectError: If the project's Android directory is not generated.
    """
    if not generated(project):
        raise ProjectError(
            "this project owns its Android directory; it is not regenerated",
            android_dir=str(project.android_root),
        )
    generation = plan(project)
    root = project.android_root
    record = root / RECORD
    previous = (
        json.loads(record.read_text(encoding="utf-8")) if record.is_file() else {}
    )
    changed = []
    for path, content in sorted(generation.files.items()):
        target = root / path
        if target.is_file() and target.read_bytes() == content:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        if path == "gradlew":
            target.chmod(0o755)
        changed.append(path)
    for path in sorted(set(previous.get("files", {})) - set(generation.files)):
        (root / path).unlink(missing_ok=True)
        changed.append(path)
    _local_properties(root)
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(
        json.dumps({"files": generation.sources}, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return changed


def explain(project: Project, path: str) -> list[str]:
    """What produced one file of the generated project.

    Args:
        project: The app.
        path: The file, relative to the Android project or the app root.

    Returns:
        Its sources: config keys, the template version, resources.

    Raises:
        ProjectError: If the project was never generated or the file is not one.
    """
    record = project.android_root / RECORD
    if not record.is_file():
        raise ProjectError("the Android project has not been generated; run prebuild")
    sources: dict[str, list[str]] = json.loads(record.read_text(encoding="utf-8"))[
        "files"
    ]
    relative = path.removeprefix(f"{GENERATED}/")
    if relative not in sources:
        raise ProjectError("not a generated file", path=path)
    return sources[relative]


def template_files() -> Iterator[tuple[str, bytes]]:
    """Every file the template contributes to the Android project.

    Yields:
        tuple[str, bytes]: Each file's path in the project, and its bytes.
    """
    template = files("pycompose").joinpath("templates", "android")
    pending = [
        (entry, entry.name)
        for entry in template.iterdir()
        if entry.name not in _TEMPLATE_ONLY and not entry.name.startswith(".")
    ]
    while pending:
        entry, path = pending.pop()
        if entry.is_dir():
            pending.extend((child, f"{path}/{child.name}") for child in entry.iterdir())
        elif entry.is_file() and entry.name not in {".gitkeep", ".DS_Store"}:
            yield path, entry.read_bytes()


def _template_version(template: Traversable) -> str:
    import tomllib

    manifest = tomllib.loads(template.joinpath("template.toml").read_text("utf-8"))
    return str(manifest["template_version"])


def _libraries(project: Project, generation: Generation) -> None:
    """The app's own Compose libraries, from its lock slice (``pycompose add``)."""
    lock = project.root / APP_LOCK
    if not lock.is_file():
        return
    libraries = json.loads(lock.read_text(encoding="utf-8")).get("libraries", [])
    if libraries:
        content = "".join(f"{library}\n" for library in libraries).encode()
        generation.add("compose-libraries.txt", content, APP_LOCK)


def _fragments(project: Project, generation: Generation) -> None:
    """Merge the app's raw fragments: a manifest module and a resource overlay."""
    overlay = project.root / _OVERLAY
    if overlay.is_dir():
        for source in sorted(overlay.rglob("*")):
            if not source.is_file():
                continue
            path = f"host/src/main/res/{source.relative_to(overlay).as_posix()}"
            if path in generation.files:
                raise ProjectError(
                    "a resource fragment cannot replace a generated file",
                    fragment=source.relative_to(project.root).as_posix(),
                    generated=path,
                )
            generation.add(path, source.read_bytes(), _OVERLAY)
    manifest = project_path(project.root, _FRAGMENT)
    if manifest.is_file():
        # AGP merges a library's manifest into the app's, with its merge rules
        # and markers, so the fragment is merged, never pasted.
        generation.add(
            "fragments/src/main/AndroidManifest.xml", manifest.read_bytes(), _FRAGMENT
        )
        generation.add("fragments/build.gradle.kts", _FRAGMENT_MODULE, _FRAGMENT)


def _plugins(project: Project, generation: Generation) -> None:
    """Merge what the app's build plugins add (plan 31 §21.6)."""
    model = run_plugins(project)
    if model == AndroidModel():
        return
    manifest = generation.files[_MANIFEST].decode()
    generation.files[_MANIFEST] = manifest_with(manifest, model).encode()
    generation.sources[_MANIFEST].append("[android] plugins")
    for name, content in sorted(model.resources.items()):
        path = f"host/src/main/res/{name}"
        if path in generation.files:
            raise ProjectError(
                "a build plugin cannot replace a generated file", path=path
            )
        generation.add(path, content, "[android] plugins")


_FRAGMENT_MODULE = b"""// Generated by pycompose from android/manifest.xml.
// Edits are discarded on the next build.
plugins {
    alias(libs.plugins.android.library)
}

extensions.configure<com.android.build.api.dsl.LibraryExtension> {
    namespace = "com.pycompose.fragments"
    compileSdk = 37
    defaultConfig {
        minSdk = 24
    }
}
"""


def _local_properties(root: Path) -> None:
    """Point Gradle at an Android SDK, unless the project already names one."""
    from pycompose.cli.toolchain import android_sdk

    target = root / "local.properties"
    sdk = android_sdk()
    if sdk is not None and not target.exists():
        target.write_text(f"sdk.dir={sdk.as_posix()}\n", encoding="utf-8")
