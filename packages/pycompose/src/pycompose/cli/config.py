"""Read and rewrite the app facts that live outside Python: name and version.

The launcher name is a resource string (``resources/strings.json``) and the
identity and version live in ``[app]`` of ``pycompose.toml``. Both files are
rewritten in place: every other key, and every comment, survives a change,
because the alternative -- regenerating them -- would throw away whatever a
person added to their own project.

Nothing here rebuilds or reinstalls the app. An identity change takes effect
in the next build; that is a Gradle and adb concern, not a config one.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from pycompose.cli.project import Project, ProjectError, project_path

KEYS = ("label", "application_id", "version_name", "version_code")
_APP_KEYS = ("application_id", "version_name", "version_code")
_LABEL_KEY = '"app_name"'
_STRING_VALUE = re.compile(r'("app_name"\s*:\s*)"(?:[^"\\]|\\.)*"')
_PACKAGE = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class Setting:
    """One configurable app fact and the file that holds it.

    Attributes:
        key: Name accepted by ``pycompose config set``.
        value: Current value; empty when the source does not define it.
        source: Project-relative file the value lives in.
    """

    key: str
    value: str
    source: str


def settings(project: Project) -> tuple[Setting, ...]:
    """Read the app's name, identity and version with their sources.

    Args:
        project: Project whose settings are read.

    Returns:
        One entry per :data:`KEYS`, in declaration order.
    """
    app = project.table("app")
    values = {
        "label": _read_label(project) or "",
        "application_id": _text(app.get("application_id")),
        "version_name": _text(app.get("version_name")),
        "version_code": _text(app.get("version_code")),
    }
    label_source = _label_path(project).relative_to(project.root).as_posix()
    return tuple(
        Setting(
            key=key,
            value=values[key],
            source=label_source if key == "label" else "pycompose.toml",
        )
        for key in KEYS
    )


def change(project: Project, key: str, value: str) -> Setting:
    """Validate one setting and write it into its source file.

    Args:
        project: Project to rewrite.
        key: One of :data:`KEYS`.
        value: New value, as typed on a command line.

    Returns:
        The setting with its new value and its source file.

    Raises:
        ProjectError: If the key is unknown or the value invalid for it.
    """
    if key == "label":
        path = _write_label(project, _validate_label(value))
        return Setting(key, value, path.relative_to(project.root).as_posix())
    if key == "application_id":
        literal = json.dumps(_validate_package(value))
        return _write_app(project, key, literal, value)
    if key == "version_name":
        literal = json.dumps(_validate_version_name(value))
        return _write_app(project, key, literal, value)
    if key == "version_code":
        code = _validate_version_code(value)
        return _write_app(project, key, str(code), str(code))
    raise ProjectError("unknown setting", setting=key, known=list(KEYS))


def _text(value: object) -> str:
    return str(value) if isinstance(value, str | int) else ""


def _label_path(project: Project) -> Path:
    directory = project.table("resources").get("path", "resources")
    if not isinstance(directory, str) or not directory:
        raise ProjectError("resources.path must be a directory name")
    return project_path(project.root, f"{directory}/strings.json")


def _read_label(project: Project) -> str | None:
    try:
        data = json.loads(_label_path(project).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get(_LABEL_KEY.strip('"')) if isinstance(data, dict) else None
    return value if isinstance(value, str) else None


def _validate_label(value: str) -> str:
    if not value or _CONTROL.search(value):
        raise ProjectError("the label must be a nonempty single-line string")
    return value


def _validate_package(value: str) -> str:
    if _PACKAGE.fullmatch(value) is None:
        raise ProjectError("application_id must be an Android package name")
    return value


def _validate_version_name(value: str) -> str:
    if not value or _CONTROL.search(value):
        raise ProjectError("version_name must be a nonempty single-line string")
    return value


def _validate_version_code(value: str) -> int:
    if re.fullmatch(r"\d+", value) is None:
        raise ProjectError("version_code must be a positive integer")
    code = int(value)
    if not 1 <= code <= 2_100_000_000:
        raise ProjectError("version_code must be a positive Android version code")
    return code


def _write_label(project: Project, value: str) -> Path:
    """Set app_name inside the strings file, leaving everything else alone."""
    path = _label_path(project)
    try:
        original = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProjectError(
            "resources/strings.json is missing; pycompose init writes one", path=path
        ) from exc
    literal = json.dumps(value, ensure_ascii=False)
    updated, replaced = _STRING_VALUE.subn(
        lambda match: match.group(1) + literal, original, count=1
    )
    if not replaced:
        updated = _insert_label(original, value, path)
    _write_text(path, updated)
    return path


def _insert_label(original: str, value: str, path: Path) -> str:
    """Add app_name to a strings file that does not define it yet."""
    try:
        data = json.loads(original)
    except ValueError as exc:
        raise ProjectError(
            "the resources strings file is not valid JSON", path=path
        ) from exc
    if not isinstance(data, dict):
        raise ProjectError(
            "the resources strings file must be a JSON object", path=path
        )
    data["app_name"] = value
    compact = "\n" not in original.strip()
    indent = None if compact else 2
    return json.dumps(data, ensure_ascii=False, indent=indent) + "\n"


def _write_app(project: Project, key: str, literal: str, value: str) -> Setting:
    """Rewrite one app.* assignment in pycompose.toml, leaving the rest alone."""
    path = project_path(project.root, "pycompose.toml")
    try:
        original = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProjectError("cannot read pycompose.toml", path=path) from exc
    _write_text(path, _toml_set(original, "app", key, literal))
    return Setting(key, value, "pycompose.toml")


def _toml_set(text: str, section: str, key: str, literal: str) -> str:
    """Replace one ``key = ...`` line inside ``section``.

    Args:
        text: Full TOML document.
        section: Table the key belongs to.
        key: Key to repoint at the new literal.
        literal: Rendered TOML value.

    Returns:
        The document with the assignment rewritten.

    Raises:
        ProjectError: If the table or the key is not in the document.
    """
    lines = text.splitlines(keepends=True)
    current = ""
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped.strip("[]").strip()
            continue
        if current == section and re.match(rf"\s*{re.escape(key)}\s*=", line):
            lines[index] = f"{key} = {literal}\n"
            return "".join(lines)
    raise ProjectError(
        f"pycompose.toml has no {section}.{key}; add it or create a fresh project"
    )


def _write_text(path: Path, text: str) -> None:
    try:
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise ProjectError("cannot write project file", path=path) from exc
