"""``[theme]`` becomes the app's Material theme: colours, fonts, shapes, dark mode.

Python already reads theme roles (``ThemeColor("primary")``,
``ThemeTypography("titleLarge")``, ``ThemeShape("medium")``); this module is
where the app says what those roles hold. The theme is fixed for the app's
lifetime, so it is generated into the Android project at build time rather
than carried in every snapshot:

- ``colors`` names a JSON file in Material Theme Builder's export format, whose
  ``schemes.light`` and ``schemes.dark`` map colour roles to ``#RRGGBB``. A
  scheme may name only some roles; the rest keep Material's defaults.
- ``dynamic`` prefers the wallpaper's colours on Android 12+. It defaults to on
  without a ``colors`` file and off with one.
- ``dark`` is ``system``, ``light`` or ``dark``.
- ``[theme.fonts]`` names a font in ``resources/fonts`` for ``display``
  (display, headline and title styles) and ``body`` (body and label styles).
- ``[theme.shapes]`` sets corner radii in dp for the five shape sizes.

The output is one Kotlin file the host's ``PyComposeTheme`` reads. The
template ships this file as generated from an empty ``[theme]``.
"""

from __future__ import annotations

import re
from functools import cache

from pycompose.cli.project import Project, ProjectError, project_path, read_json
from pycompose.cli.resources import MAIN, RESOURCE_NAME
from pycompose.contract.catalog import lock

PATH = f"{MAIN}/kotlin/com/pycompose/host/ui/AppTheme.kt"
"""Where the generated theme lives, relative to the Android project."""

_HEX = re.compile(r"#[0-9a-fA-F]{6}")
_DARK = {"system": "null", "light": "false", "dark": "true"}
_SHAPES = ("extra_small", "small", "medium", "large", "extra_large")
_FONTS = {
    "display": ("display", "headline", "title"),
    "body": ("body", "label"),
}
_SIZES = ("Large", "Medium", "Small")
_IGNORED_ROLES = frozenset({"shadow"})
"""Roles Theme Builder exports that Material 3's ColorScheme does not have."""


@cache
def _roles() -> frozenset[str]:
    """The colour roles of the pinned ColorScheme, as the catalog lists them."""
    name = lock()["valueTypes"]["ThemeColor"]["parameters"]["name"]
    return frozenset(name["values"])


def theme_files(project: Project) -> dict[str, bytes]:
    """The generated theme ``[theme]`` describes, by Android path.

    Args:
        project: The app.

    Returns:
        The theme file relative to the Android project.
    """
    return {PATH: render(project).encode("utf-8")}


def render(project: Project | None) -> str:
    """The Kotlin source for an app's theme; Material's defaults without one.

    Args:
        project: The app, or None for the template's default theme.

    Returns:
        The source of ``AppTheme.kt``.

    Raises:
        ProjectError: If any ``[theme]`` value is invalid.
    """
    table = project.table("theme") if project is not None else {}
    unknown = set(table) - {"colors", "dynamic", "dark", "fonts", "shapes"}
    if unknown:
        raise ProjectError("unknown theme key", key=f"theme.{sorted(unknown)[0]}")
    schemes = _schemes(project, table.get("colors")) if project else {}
    dynamic = table.get("dynamic", "colors" not in table)
    if not isinstance(dynamic, bool):
        raise ProjectError("theme.dynamic must be true or false")
    dark = table.get("dark", "system")
    if not isinstance(dark, str) or dark not in _DARK:
        raise ProjectError("theme.dark must be system, light or dark", value=str(dark))
    fonts = _fonts(project, table.get("fonts", {})) if project else {}
    shapes = _shapes(table.get("shapes", {}))
    lines = [
        "// Generated from [theme] in pycompose.toml. Do not edit.",
        "package com.pycompose.host.ui",
        "",
        *_imports(schemes, fonts, shapes),
        "",
        "/** The app's Material theme, read by [PyComposeTheme]. */",
        "internal object AppTheme {",
        "    /** Prefer the wallpaper's colours on Android 12+. */",
        f"    const val DYNAMIC: Boolean = {'true' if dynamic else 'false'}",
        "",
        "    /** Forced dark mode, or null to follow the system. */",
        f"    val darkMode: Boolean? = {_DARK[dark]}",
        "",
        *_scheme("light", schemes.get("light")),
        "",
        *_scheme("dark", schemes.get("dark")),
        "",
        *_typography(fonts),
        "",
        *_shape_lines(shapes),
        "}",
    ]
    return "\n".join(lines) + "\n"


def _schemes(project: Project, source: object) -> dict[str, dict[str, str]]:
    if source is None:
        return {}
    if not isinstance(source, str):
        raise ProjectError("theme.colors must be a path to a JSON file")
    path = project_path(project.root, source)
    if not path.is_file():
        raise ProjectError("theme.colors file is missing", path=source)
    document = read_json(path)
    schemes = document.get("schemes") if isinstance(document, dict) else None
    if not isinstance(schemes, dict):
        raise ProjectError("theme.colors has no 'schemes' object", path=source)
    result = {}
    for name in ("light", "dark"):
        scheme = schemes.get(name, {})
        if not isinstance(scheme, dict):
            raise ProjectError("a theme scheme must be an object", scheme=name)
        roles = {}
        for role, value in scheme.items():
            if role in _IGNORED_ROLES:
                continue
            if role not in _roles():
                raise ProjectError("unknown colour role", scheme=name, role=role)
            if not isinstance(value, str) or _HEX.fullmatch(value) is None:
                raise ProjectError(
                    "a colour role must be #RRGGBB", scheme=name, role=role
                )
            roles[role] = value[1:].upper()
        result[name] = roles
    return result


def _fonts(project: Project, table: object) -> dict[str, str]:
    if not isinstance(table, dict):
        raise ProjectError("theme.fonts must be a table")
    configured = project.table("resources").get("path", "resources")
    folder = project_path(project.root, f"{configured}/fonts")
    result = {}
    for slot, name in table.items():
        if slot not in _FONTS:
            raise ProjectError("unknown theme font slot", key=f"theme.fonts.{slot}")
        if not isinstance(name, str) or RESOURCE_NAME.fullmatch(name) is None:
            raise ProjectError(
                "a theme font is a font's file name without its extension"
            )
        if not any((folder / f"{name}{ext}").is_file() for ext in (".ttf", ".otf")):
            raise ProjectError(
                "theme font is not in resources/fonts as .ttf or .otf",
                key=f"theme.fonts.{slot}",
                font=name,
            )
        result[slot] = name
    return result


def _shapes(table: object) -> dict[str, int]:
    if not isinstance(table, dict):
        raise ProjectError("theme.shapes must be a table")
    result = {}
    for size, radius in table.items():
        if size not in _SHAPES:
            raise ProjectError("unknown theme shape size", key=f"theme.shapes.{size}")
        if type(radius) is not int or not 0 <= radius <= 1000:
            raise ProjectError(
                "a theme shape is a corner radius in dp, 0 to 1000",
                key=f"theme.shapes.{size}",
            )
        result[size] = radius
    return result


def _imports(
    schemes: dict[str, dict[str, str]], fonts: dict[str, str], shapes: dict[str, int]
) -> list[str]:
    names = {
        "androidx.compose.material3.ColorScheme",
        "androidx.compose.material3.Shapes",
        "androidx.compose.material3.Typography",
    }
    if any(schemes.values()):
        names.add("androidx.compose.ui.graphics.Color")
    if schemes.get("light"):
        names.add("androidx.compose.material3.lightColorScheme")
    if schemes.get("dark"):
        names.add("androidx.compose.material3.darkColorScheme")
    if fonts:
        names |= {
            "androidx.compose.ui.text.font.Font",
            "androidx.compose.ui.text.font.FontFamily",
            "com.pycompose.host.R",
        }
    if shapes:
        names |= {
            "androidx.compose.foundation.shape.RoundedCornerShape",
            "androidx.compose.ui.unit.dp",
        }
    return [f"import {name}" for name in sorted(names)]


def _scheme(name: str, roles: dict[str, str] | None) -> list[str]:
    doc = f"    /** The {name} colours, or null for Material's defaults. */"
    if not roles:
        return [doc, f"    val {name}Colors: ColorScheme? = null"]
    body = [f"            {role} = Color(0xFF{roles[role]})," for role in sorted(roles)]
    return [
        doc,
        f"    val {name}Colors: ColorScheme? =",
        f"        {name}ColorScheme(",
        *body,
        "        )",
    ]


def _typography(fonts: dict[str, str]) -> list[str]:
    if not fonts:
        return ["    val typography: Typography = Typography()"]
    lines = [
        f"    private val {slot}Font = FontFamily(Font(R.font.{fonts[slot]}))"
        for slot in sorted(fonts)
    ]
    lines += [
        "",
        "    private val base = Typography()",
        "",
        "    val typography: Typography =",
    ]
    lines.append("        Typography(")
    for slot, groups in _FONTS.items():
        if slot not in fonts:
            continue
        for group in groups:
            for size in _SIZES:
                style = f"{group}{size}"
                lines.append(
                    f"            {style} = base.{style}.copy(fontFamily = {slot}Font),"
                )
    lines.append("        )")
    return lines


def _shape_lines(shapes: dict[str, int]) -> list[str]:
    if not shapes:
        return ["    val shapes: Shapes = Shapes()"]
    lines = ["    val shapes: Shapes =", "        Shapes("]
    for size in _SHAPES:
        if size in shapes:
            camel = re.sub(r"_(\w)", lambda m: m.group(1).upper(), size)
            lines.append(
                f"            {camel} = RoundedCornerShape({shapes[size]}.dp),"
            )
    lines.append("        )")
    return lines
