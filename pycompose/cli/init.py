"""Create projects by copying packaged, versioned template assets."""

from __future__ import annotations

import json
import re
import tomllib
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from pycompose.errors import PyComposeError
from pycompose.ir.generated_validators import SCHEMA_VERSION
from pycompose.version import __version__


class InitError(PyComposeError):
    """The project name or packaged template is invalid."""


def _copy_assets(source: Traversable, target: Path) -> None:
    for asset in sorted(source.iterdir(), key=lambda entry: entry.name):
        destination = target / asset.name
        if asset.is_dir():
            destination.mkdir()
            _copy_assets(asset, destination)
        elif asset.is_file():
            with destination.open("xb") as output:
                output.write(asset.read_bytes())
            if asset.name == "gradlew":
                destination.chmod(0o755)


def init_project(name: str, *, directory: Path) -> tuple[Path, bool, bool]:
    """Copy template assets and write config without replacing existing work.

    Args:
        name: Single project-directory name, starting with an ASCII letter.
        directory: Parent directory in which to create the project.

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
    config = (
        f"[app]\nname = {quoted}\napplication_id = {app_id}\n"
        'version_name = "0.1.0"\nversion_code = 1\n\n'
        '[python]\nentrypoint = "main:app"\nsource_dir = "app"\n\n'
        '[resources]\npath = "resources"\n\n'
        '[signing]\nkeystore = ""\nkey_alias = ""\n'
        'store_password_env = "PYCOMPOSE_STORE_PASSWORD"\n'
        'key_password_env = "PYCOMPOSE_KEY_PASSWORD"\n\n'
        f'[toolchain]\nlibrary_version = "{__version__}"\n'
        f'schema_version = "{SCHEMA_VERSION}"\n'
        f"template_version = {json.dumps(template_version)}\n"
    )
    try:
        target.mkdir()
    except FileExistsError:
        if target.is_dir():
            return target, False, False
        raise
    _copy_assets(template, target)
    with (target / "pycompose.toml").open(
        "x", encoding="utf-8", newline="\n"
    ) as output:
        output.write(config)
    return target, True, android_scaffold
