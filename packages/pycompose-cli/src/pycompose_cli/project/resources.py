"""Deterministic resource translation; JSON strings are literal Android strings."""

from __future__ import annotations

import re
from pathlib import Path
from xml.sax.saxutils import escape

from pycompose_cli.project import Project, ProjectError, project_path, read_json

RESOURCE_NAME = re.compile(r"[a-z][a-z0-9_]*")
DENSITIES = frozenset(
    {"ldpi", "mdpi", "tvdpi", "hdpi", "xhdpi", "xxhdpi", "xxxhdpi", "nodpi", "anydpi"}
)
MAIN = "host/src/main"


def _values_dir(filename: str) -> str:
    if filename == "strings.json":
        return "values"
    locale = filename.removeprefix("strings.").removesuffix(".json")
    parts = re.split(r"[-_]", locale)
    if re.fullmatch(r"[a-z]{2,3}", parts[0]) is None:
        raise ProjectError("invalid string locale", file=filename)
    if len(parts) == 1:
        return f"values-{locale}"
    if len(parts) == 2 and re.fullmatch(r"(?:r)?[A-Z]{2}", parts[1]):
        return f"values-{parts[0]}-r{parts[1].removeprefix('r')}"
    if re.fullmatch(
        r"[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-(?:[A-Z]{2}|[0-9]{3}))?", "-".join(parts)
    ):
        return "values-b+" + "+".join(parts)
    raise ProjectError("invalid string locale", file=filename)


def _strings(path: Path) -> bytes:
    data = read_json(path)
    if not isinstance(data, dict):
        raise ProjectError("strings JSON must be an object", file=path.name)
    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<resources>"]
    for key, value in sorted(data.items()):
        if (
            not isinstance(key, str)
            or RESOURCE_NAME.fullmatch(key) is None
            or not isinstance(value, str)
        ):
            raise ProjectError(
                "strings must have Android resource names and string values",
                file=path.name,
                key=key,
            )
        if any(
            not (
                char in "\t\n\r"
                or 0x20 <= ord(char) <= 0xD7FF
                or 0xE000 <= ord(char) <= 0xFFFD
                or 0x10000 <= ord(char) <= 0x10FFFF
            )
            for char in value
        ):
            raise ProjectError(
                "string contains an invalid XML character", file=path.name, key=key
            )
        text = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\t", "\\t")
            .replace("\r", "\\u000d")
            .replace("@", "\\@")
            .replace("?", "\\?")
        )
        lines.append(
            f'    <string name="{key}" formatted="false">"{escape(text)}"</string>'
        )
    return ("\n".join(lines) + "\n</resources>\n").encode("utf-8")


def _binary_target(relative: Path) -> str:
    group, *parts = relative.parts
    if not parts:
        raise ProjectError("resource group must be a directory", path=relative)
    if group == "assets":
        return f"{MAIN}/assets/" + "/".join(parts)
    if group == "fonts":
        folder = "font"
        allowed = {".ttf", ".otf", ".xml"}
    elif group == "drawables":
        folder = "drawable"
        allowed = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".xml"}
        if len(parts) == 2:
            density = parts.pop(0).removeprefix("drawable-")
            if density not in DENSITIES:
                raise ProjectError("unknown drawable density", path=relative)
            folder += "-" + density
    else:
        raise ProjectError("unsupported resource file", path=relative)
    filename = Path(parts[-1])
    name = (
        filename.stem.removesuffix(".9") if filename.suffix == ".png" else filename.stem
    )
    if (
        len(parts) != 1
        or filename.suffix not in allowed
        or RESOURCE_NAME.fullmatch(name) is None
    ):
        raise ProjectError("invalid Android resource filename", path=relative)
    return f"{MAIN}/res/{folder}/{filename.name}"


def resource_files(project: Project) -> dict[str, bytes]:
    """Translate resources into a complete, deterministic output plan.

    Args:
        project: Project whose resources.path is a project-local directory.

    Returns:
        Project-relative output filenames and their exact bytes.

    Raises:
        ProjectError: If names, locales, JSON or source paths are invalid.
    """
    configured = project.table("resources").get("path", "resources")
    if not isinstance(configured, str):
        raise ProjectError("resources.path must be a string")
    root = project_path(project.root, configured)
    if not root.is_dir():
        raise ProjectError("resources directory is missing", path=configured)
    output: dict[str, bytes] = {}
    identities: set[tuple[str, str]] = set()
    for source in sorted(root.rglob("*")):
        project_path(project.root, source.relative_to(project.root).as_posix())
        if not source.is_file() or source.name in {".gitkeep", ".DS_Store"}:
            continue
        relative = source.relative_to(root)
        if relative.parts[0] == "android":
            # Raw Android fragments, merged by the generated project.
            continue
        if len(relative.parts) == 1 and (
            source.name == "strings.json"
            or source.name.startswith("strings.")
            and source.suffix == ".json"
        ):
            target = f"{MAIN}/res/{_values_dir(source.name)}/strings.xml"
            value = _strings(source)
        else:
            target = _binary_target(relative)
            value = source.read_bytes()
        identity = (str(Path(target).parent), Path(target).stem.removesuffix(".9"))
        if target in output or identity in identities:
            raise ProjectError("duplicate resource output/name", path=target)
        identities.add(identity)
        output[target] = value
    prefix = project.android_root.relative_to(project.root)
    return {(prefix / name).as_posix(): value for name, value in output.items()}
