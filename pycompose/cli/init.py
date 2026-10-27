"""Create projects by copying packaged, versioned template assets."""

from __future__ import annotations

import json
import re
import tomllib
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from pycompose.contract.catalog import SCHEMA_VERSION
from pycompose.errors import PyComposeError
from pycompose.version import __version__


class InitError(PyComposeError):
    """The project name or packaged template is invalid."""


def _copy_assets(
    source: Traversable, target: Path, *, android_root: Path | None = None
) -> None:
    """Copy the template: the app's files to ``target``, Android files beside them.

    Without ``android_root`` only the app's own files are copied -- its Python,
    its resources and its dotfiles -- since the Android project is generated.
    """
    for asset in sorted(source.iterdir(), key=lambda entry: entry.name):
        android = asset.name not in {"app", "resources"} and not asset.name.startswith(
            "."
        )
        if android and android_root is None:
            continue
        _copy(asset, (android_root if android else None) or target)


def _copy(asset: Traversable, base: Path) -> None:
    destination = base / asset.name
    if asset.is_dir():
        destination.mkdir()
        for child in sorted(asset.iterdir(), key=lambda entry: entry.name):
            _copy(child, destination)
    elif asset.is_file():
        with destination.open("xb") as output:
            output.write(asset.read_bytes())
        if asset.name == "gradlew":
            destination.chmod(0o755)


def _generate_slice(target: Path, android_root: Path) -> None:
    """Generate the sample app's component slice so the scaffold is complete.

    ``pycompose build`` regenerates the slice before every build, but a project
    that has never been built is still expected to work: the packaged smoke
    checks and a user's first script import the sample entrypoint, which needs
    its generated package (ADR-0014).

    Args:
        target: The project root that was just scaffolded.
        android_root: Native build root that consumes the generated Kotlin.

    Raises:
        InitError: If the slice cannot be generated from the packaged catalog.
    """
    import io
    from contextlib import redirect_stderr, redirect_stdout

    from pycompose.codegen.app_slice import uses_generated_slice
    from pycompose.codegen.main import build_app

    app = target / "app"
    if not uses_generated_slice(app):
        return
    output = io.StringIO()
    with redirect_stdout(output), redirect_stderr(output):
        code = build_app(app, android_root=android_root)
    if code:
        raise InitError(
            "component slice generation failed:\n" + output.getvalue().strip()
        )


def init_project(
    name: str, *, directory: Path, native: bool = False
) -> tuple[Path, bool, bool]:
    """Copy template assets and write config without replacing existing work.

    Args:
        name: Single project-directory name, starting with an ASCII letter.
        directory: Parent directory in which to create the project.
        native: Expose the Android scaffold at the project root for customization.

    Returns:
        Project path, whether it was created, and Android scaffold availability.

    Raises:
        InitError: If the name or template manifest is invalid.
        FileExistsError: If a non-directory project path appears during creation.
    """
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,62}", name) is None:
        raise InitError(
            "name must start with a letter and contain only letters, digits, "
            "underscores or hyphens (at most 63 characters)"
        )
    target = directory / name
    if target.is_dir():
        return target, False, False
    if target.exists() or target.is_symlink():
        raise InitError(
            "project path already exists and is not a directory", path=target
        )
    template = files("pycompose").joinpath("templates", "android")
    try:
        manifest = tomllib.loads(
            template.joinpath("template.toml").read_text(encoding="utf-8")
        )
        template_version = manifest["template_version"]
        android_scaffold = manifest["android_scaffold"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        raise InitError("packaged Android template is unavailable or invalid") from exc
    if not isinstance(template_version, str) or not isinstance(android_scaffold, bool):
        raise InitError("invalid template manifest fields")
    quoted = json.dumps(name)
    app_id = json.dumps("com.example.app_" + name.lower().replace("-", "_"))
    android_dir = "." if native else ".pycompose/android"
    config = (
        f"[app]\nname = {quoted}\napplication_id = {app_id}\n"
        'version_name = "0.1.0"\nversion_code = 1\n\n'
        '[python]\nentrypoint = "main:app"\nsource_dir = "app"\n'
        "# Packages installed into the app at build time. Pip resolves them then,\n"
        "# from PyPI and Chaquopy's index, so pin exact versions (==) when a build\n"
        "# must be reproducible. Pure Python packages and Android wheels for\n"
        "# Python 3.12 on arm64-v8a and x86_64 install; a package with native code\n"
        "# needs an Android wheel, and the build fails listing the available\n"
        "# versions when there is none. Changing this list changes the app and\n"
        "# needs a rebuild, not a hot reload.\n"
        "requirements = []\n\n"
        '[resources]\npath = "resources"\n\n'
        '[signing]\nkeystore = ""\nkey_alias = ""\n'
        'store_password_env = "PYCOMPOSE_STORE_PASSWORD"\n'
        'key_password_env = "PYCOMPOSE_KEY_PASSWORD"\n\n'
        f'[toolchain]\nlibrary_version = "{__version__}"\n'
        f'schema_version = "{SCHEMA_VERSION}"\n'
        f"template_version = {json.dumps(template_version)}\n"
        f"android_dir = {json.dumps(android_dir)}\n"
    )
    try:
        target.mkdir()
    except FileExistsError:
        if target.is_dir():
            return target, False, False
        raise
    android_root = target / android_dir
    android_root.mkdir(parents=True, exist_ok=True)
    # A native project owns its Android files; any other is generated from the
    # app on every build (plan 31 §21), so only the app's own files are copied.
    _copy_assets(template, target, android_root=android_root if native else None)
    # The launcher label is an app string like any other, so it flows through
    # the same resource pipeline and localizes with it.
    with (target / "resources" / "strings.json").open(
        "w", encoding="utf-8", newline="\n"
    ) as output:
        output.write(json.dumps({"app_name": name}) + "\n")
    with (target / "pycompose.toml").open(
        "x", encoding="utf-8", newline="\n"
    ) as output:
        output.write(config)
    if not native:
        from pycompose.cli.prebuild import prebuild
        from pycompose.cli.project import load_project

        prebuild(load_project(target))
    if android_scaffold:
        _generate_slice(target, android_root)
    return target, True, android_scaffold
