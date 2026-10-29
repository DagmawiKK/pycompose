"""``pycompose migrate``: turn an app-owned Android project into a generated one.

Every file of the old project is accounted for (plan 31 §21.8): identical to
the template, or a resource output, it is regenerated; a launcher icon becomes
``[app] icon`` from one SVG; any other resource the app added becomes a raw
resource fragment; a manifest that only adds the app's chosen permissions is
regenerated. Anything else -- an edited template file, Kotlin, Gradle -- is
refused with its path, and then nothing is changed. Only when nothing is
refused are the fragments and the SVG written, ``android_dir`` switched to the
generated project, and the old files deleted: exactly the ones accounted for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree.ElementTree import Element

from defusedxml import ElementTree

from pycompose.cli.permissions import selected_permissions, with_permissions
from pycompose.cli.prebuild import GENERATED, generated, prebuild, template_files
from pycompose.cli.project import Project, ProjectError, load_project
from pycompose.cli.resources import resource_files

_ANDROID = "{http://schemas.android.com/apk/res/android}"
_RES = "host/src/main/res/"
_MANIFEST = "host/src/main/AndroidManifest.xml"
_SKIPPED = frozenset(
    {"build", ".gradle", ".kotlin", ".pycompose", ".idea", ".git", "local.properties"}
)
_APP = frozenset({"app", "resources", "pycompose.toml", "icon.svg", "android"})


@dataclass
class Migration:
    """What migrating found: files kept as fragments, refusals, the icon."""

    fragments: dict[str, bytes] = field(default_factory=dict)
    refused: list[str] = field(default_factory=list)
    accounted: list[Path] = field(default_factory=list)
    icon: tuple[str, str] | None = None


def migrate(project: Project) -> Migration:
    """Account for the app's Android files and, if all are, generate instead.

    Args:
        project: An app that owns its Android directory.

    Returns:
        What was found; nothing was changed when anything was refused.

    Raises:
        ProjectError: If the project is already generated.
    """
    if generated(project):
        raise ProjectError("this project's Android directory is already generated")
    found = _survey(project)
    if found.refused:
        return found
    root = project.root
    for name, content in found.fragments.items():
        target = root / "resources/android/res" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    config = (root / "pycompose.toml").read_text(encoding="utf-8")
    if found.icon is not None:
        svg, background = found.icon
        (root / "icon.svg").write_text(svg, encoding="utf-8")
        config = _set(config, "app", "icon", '"icon.svg"')
        config = _set(config, "app", "icon_background", f'"{background}"')
    config = _set(config, "toolchain", "android_dir", f'"{GENERATED}"')
    (root / "pycompose.toml").write_text(config, encoding="utf-8")
    for path in found.accounted:
        path.unlink()
    _prune(project.android_root)
    prebuild(load_project(root))
    return found


def _survey(project: Project) -> Migration:
    found = Migration()
    android = project.android_root
    template = dict(template_files())
    prefix = android.relative_to(project.root).as_posix()
    outputs = {
        name.removeprefix(f"{prefix}/") if prefix != "." else name
        for name in resource_files(project)
    }
    icons: dict[str, bytes] = {}
    for path in sorted(android.rglob("*")):
        relative = path.relative_to(android)
        top = relative.parts[0]
        if not path.is_file() or top in _SKIPPED or "build" in relative.parts:
            continue
        if android == project.root and (top in _APP or top.startswith(".")):
            continue
        name = relative.as_posix()
        content = path.read_bytes()
        found.accounted.append(path)
        if name in outputs or name == "template.toml" or template.get(name) == content:
            continue
        if name == _MANIFEST and _only_permissions(project, template[name], content):
            continue
        if name.startswith(_RES) and Path(name).name.startswith("app_icon"):
            icons[name.removeprefix(_RES)] = content
        elif name.startswith(_RES) and name not in template:
            found.fragments[name.removeprefix(_RES)] = content
        else:
            found.refused.append(f"{name}: differs from the template; it has no key")
    if icons:
        try:
            found.icon = _icon(icons)
        except ProjectError as exc:
            found.refused.append(f"launcher icon: {exc}")
    return found


def _only_permissions(project: Project, template: bytes, content: bytes) -> bool:
    chosen = selected_permissions(project)
    return with_permissions(template.decode(), chosen).encode() == content


def _icon(icons: dict[str, bytes]) -> tuple[str, str]:
    """The SVG and background colour an app's vector launcher icon was."""
    foreground = icons.get("drawable/app_icon_foreground.xml")
    background = icons.get("drawable/app_icon_background.xml")
    if foreground is None or background is None:
        raise ProjectError("needs app_icon_foreground and app_icon_background vectors")
    width, height, paths = _vector(foreground)
    _, _, fills = _vector(background)
    colors = {p.get(f"{_ANDROID}fillColor") for p in fills}
    if len(colors) != 1 or None in colors:
        raise ProjectError("the background must be one solid colour")
    body = "".join(_svg_path(p) for p in paths)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">\n'
        f"{body}</svg>\n"
    )
    return svg, str(colors.pop()).upper()


def _vector(content: bytes) -> tuple[str, str, list[Element]]:
    root = ElementTree.fromstring(content)
    if root.tag != "vector" or any(child.tag != "path" for child in root):
        raise ProjectError("only flat vector drawables convert to SVG")
    width = root.get(f"{_ANDROID}viewportWidth")
    height = root.get(f"{_ANDROID}viewportHeight")
    return str(width), str(height), list(root)


def _svg_path(path: Element) -> str:
    attributes = {
        "d": path.get(f"{_ANDROID}pathData"),
        "fill": path.get(f"{_ANDROID}fillColor", "none"),
        "fill-rule": "evenodd"
        if path.get(f"{_ANDROID}fillType") == "evenOdd"
        else None,
        "stroke": path.get(f"{_ANDROID}strokeColor"),
        "stroke-width": path.get(f"{_ANDROID}strokeWidth"),
    }
    known = {f"{_ANDROID}{name}" for name in ("pathData", "fillColor", "fillType")}
    known |= {f"{_ANDROID}strokeColor", f"{_ANDROID}strokeWidth"}
    if set(path.attrib) - known:
        raise ProjectError("a path attribute has no SVG equivalent here")
    text = " ".join(f'{key}="{value}"' for key, value in attributes.items() if value)
    return f"  <path {text}/>\n"


def _set(config: str, table: str, key: str, literal: str) -> str:
    """Set one key of a TOML table, keeping every other line as written."""
    header = re.search(rf"^\[{re.escape(table)}\]\s*$", config, re.MULTILINE)
    if header is None:
        return config.rstrip("\n") + f"\n\n[{table}]\n{key} = {literal}\n"
    end = re.search(r"^\[", config[header.end() :], re.MULTILINE)
    stop = header.end() + (end.start() if end else len(config) - header.end())
    section = config[header.end() : stop]
    line = re.compile(rf"^{re.escape(key)}\s*=.*$", re.MULTILINE)
    if line.search(section):
        section = line.sub(f"{key} = {literal}", section, count=1)
    else:
        section = f"\n{key} = {literal}" + section
    return config[: header.end()] + section + config[stop:]


def _prune(root: Path) -> None:
    """Remove the directories migration emptied, deepest first."""
    for directory in sorted(
        (path for path in root.rglob("*") if path.is_dir()), key=lambda p: -len(p.parts)
    ):
        if (
            not any(directory.iterdir())
            and not set(directory.relative_to(root).parts) & _SKIPPED
        ):
            directory.rmdir()
