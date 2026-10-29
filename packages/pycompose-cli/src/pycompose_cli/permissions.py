"""Explicit permission selection with a generated copy of the user's manifest."""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree.ElementTree import Element

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from pycompose_cli.project import Project, ProjectError, project_path

_ANDROID = "http://schemas.android.com/apk/res/android"


def selected_permissions(project: Project) -> tuple[str, ...]:
    """Read app consent, without deriving permissions from installed packages.

    Args:
        project: App configuration with optional android.permissions.

    Returns:
        Unique explicitly requested permission names.

    Raises:
        ProjectError: If the declaration contains invalid permission names.
    """
    value = project.table("android").get("permissions", [])
    if not isinstance(value, list) or not all(
        isinstance(name, str) and re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+", name)
        for name in value
    ):
        raise ProjectError("android.permissions must be an array of permission names")
    return tuple(dict.fromkeys(value))


def _manifest(project: Project) -> tuple[str, Element]:
    source = project_path(project.android_root, "host/src/main/AndroidManifest.xml")
    try:
        text = source.read_text(encoding="utf-8")
        root = ElementTree.fromstring(text)
    except (OSError, ElementTree.ParseError, DefusedXmlException) as exc:
        raise ProjectError("cannot read native AndroidManifest.xml") from exc
    if root.tag != "manifest":
        raise ProjectError("native manifest root must be manifest")
    return text, root


def effective_permissions(project: Project) -> tuple[str, ...]:
    """Combine app consent with unconditional existing native declarations.

    Args:
        project: Selected native root and explicit app configuration.

    Returns:
        Permission names, not claims that runtime dangerous permissions are granted.

    Raises:
        ProjectError: If a selected permission conflicts with a restricted entry.
    """
    chosen = selected_permissions(project)
    _, root = _manifest(project)
    existing = []
    for entry in root.findall("uses-permission"):
        name = entry.get(f"{{{_ANDROID}}}name", "")
        restricted = entry.get(f"{{{_ANDROID}}}maxSdkVersion") is not None
        if restricted and name in chosen:
            raise ProjectError(
                "selected permission has a maxSdkVersion conflict", permission=name
            )
        if not restricted:
            existing.append(name)
    return tuple(dict.fromkeys([*existing, *chosen]))


def with_permissions(text: str, chosen: tuple[str, ...]) -> str:
    """A manifest declaring every chosen permission it does not already declare.

    Args:
        text: The manifest.
        chosen: The app's explicit permission choices.

    Returns:
        The manifest with the missing ``uses-permission`` entries added.

    Raises:
        ProjectError: If the manifest cannot be read or has no closing element.
    """
    try:
        root = ElementTree.fromstring(text)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise ProjectError("cannot read the AndroidManifest.xml") from exc
    existing = {
        entry.get(f"{{{_ANDROID}}}name") for entry in root.findall("uses-permission")
    }
    missing = sorted(set(chosen) - existing)
    if not missing:
        return text
    additions = "".join(
        f'    <uses-permission xmlns:android="{_ANDROID}" android:name="{name}" />\n'
        for name in missing
    )
    generated = text.replace("</manifest>", additions + "</manifest>")
    if generated == text:
        raise ProjectError("manifest needs an explicit closing manifest element")
    return generated


def stage_manifest(project: Project) -> Path | None:
    """Generate a manifest input without rewriting user-owned native XML.

    Args:
        project: Project whose explicit permission choices have been validated.

    Returns:
        Generated manifest path, or None when the user's manifest is sufficient.
    """
    chosen = selected_permissions(project)
    if not chosen:
        return None
    text, _ = _manifest(project)
    generated = with_permissions(text, chosen)
    if generated == text:
        return None
    path = project_path(
        project.android_root, ".pycompose/extensions/AndroidManifest.xml"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text(encoding="utf-8") != generated:
        path.write_text(generated, encoding="utf-8")
    return path
