"""Project configuration and confined filesystem paths shared by CLI commands."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

from pycompose.errors import PyComposeError
from pycompose.model.catalog.lock import (
    MIN_LIBRARY_VERSION,
    MIN_SCHEMA_VERSION,
    REGISTRY,
    SCHEMA_VERSION,
)
from pycompose.model.catalog.version import require_version
from pycompose.version import __version__


class ProjectError(PyComposeError):
    """Project configuration, resources or tool execution failed."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProjectError("duplicate JSON key", key=key)
        result[key] = value
    return result


def _invalid_constant(value: str) -> object:
    raise ProjectError("non-finite JSON number", value=value)


def read_json(path: Path) -> object:
    """Read strict JSON, rejecting ambiguous keys and non-finite numbers.

    Args:
        path: JSON input filename.

    Returns:
        Parsed JSON data.

    Raises:
        ProjectError: If JSON cannot be decoded unambiguously.
    """
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_constant,
        )
    except (ValueError, RecursionError) as exc:
        raise ProjectError("invalid JSON", file=path, reason=str(exc)) from exc


def project_path(root: Path, relative: str) -> Path:
    """Resolve a project-local path without traversing symlinks.

    Args:
        root: Absolute project root.
        relative: Project-relative file or directory name.

    Returns:
        A path strictly inside root.

    Raises:
        ProjectError: If the path is absolute, escapes root or traverses a symlink.
    """
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ProjectError(
            "path must be relative and inside the project", path=relative
        )
    candidate = root
    for part in path.parts:
        candidate /= part
        if candidate.is_symlink():
            raise ProjectError(
                "project paths must not traverse symlinks", path=relative
            )
    return candidate


@dataclass(frozen=True, slots=True)
class Project:
    """A loaded configuration, without importing the app or template.

    Attributes:
        root: Absolute project root.
        config: Parsed TOML configuration.
    """

    root: Path
    config: dict[str, object]

    @property
    def android_root(self) -> Path:
        """Return the confined native build root; old projects use the app root.

        Returns:
            The Android project directory, without creating or moving anything.

        Raises:
            ProjectError: If toolchain.android_dir is not a safe relative path.
        """
        directory = self.table("toolchain").get("android_dir", ".")
        if directory == ".":
            return self.root
        if not isinstance(directory, str) or not directory:
            raise ProjectError("toolchain.android_dir must be a relative directory")
        return project_path(self.root, directory)

    def table(self, name: str) -> dict[str, object]:
        """Read a configuration table, rejecting non-table values.

        Args:
            name: Top-level TOML table name.

        Returns:
            The table, or an empty mapping if omitted.

        Raises:
            ProjectError: If the table is not an object.
        """
        value = self.config.get(name, {})
        if not isinstance(value, dict):
            raise ProjectError("configuration section must be a table", section=name)
        return value


def load_project(directory: Path) -> Project:
    """Load pycompose.toml from the current project directory.

    Args:
        directory: Directory containing pycompose.toml.

    Returns:
        A project with parsed configuration.

    Raises:
        ProjectError: If config is missing, unreadable or malformed.
    """
    root = directory.resolve()
    try:
        config = tomllib.loads(
            project_path(root, "pycompose.toml").read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise ProjectError(
            "cannot read pycompose.toml; run from a project created with pycompose init"
        ) from exc
    if "extensions" in config:
        raise ProjectError(
            "[extensions] was removed: list Python packages in [python] requirements "
            "and Android permissions in [android] permissions"
        )
    return Project(root, config)


def check_project_versions(project: Project) -> str:
    """Reject unsupported schema versions and libraries older than the project.

    Args:
        project: Project with a toolchain table.

    Returns:
        The configured schema version.

    Raises:
        ProjectError: If required version fields are not strings.
    """
    config = project.table("toolchain")
    schema = config.get("schema_version")
    library = config.get("library_version", MIN_LIBRARY_VERSION)
    if not isinstance(schema, str) or not isinstance(library, str):
        raise ProjectError(
            "toolchain schema_version and library_version must be strings"
        )
    require_version(
        schema,
        minimum=MIN_SCHEMA_VERSION,
        maximum=SCHEMA_VERSION,
        supported=REGISTRY.supported_schema_versions or (SCHEMA_VERSION,),
    )
    require_version(__version__, minimum=library, field="library_version")
    return schema
