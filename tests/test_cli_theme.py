"""``[theme]`` generates the app's Material theme into the Android project."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pycompose.cli.prebuild import plan
from pycompose.cli.project import ProjectError, load_project
from pycompose.cli.theme import PATH, render

ROOT = Path(__file__).resolve().parents[1]
NOTES = ROOT / "examples/notes"


def _app(tmp_path: Path, theme: str, colors: object = None) -> Path:
    target = tmp_path / "notes"
    shutil.copytree(NOTES, target, ignore=shutil.ignore_patterns(".pycompose"))
    config = target / "pycompose.toml"
    # The example has a theme of its own; each test states the one it checks.
    own = "# The colours theme roles resolve to; the rest keep Material's defaults.\n"
    own += '[theme]\ncolors = "theme.json"\n'
    config.write_text(config.read_text().replace(own, "") + "\n" + theme)
    if colors is not None:
        (target / "theme.json").write_text(json.dumps(colors))
    return target


def test_the_template_ships_the_theme_an_empty_config_generates() -> None:
    template = ROOT / "android" / PATH
    assert template.read_text() == render(None)


def test_without_a_theme_the_app_keeps_materials_defaults(tmp_path: Path) -> None:
    source = render(load_project(_app(tmp_path, "")))
    assert "const val DYNAMIC: Boolean = true" in source
    assert "val darkMode: Boolean? = null" in source
    assert "val lightColors: ColorScheme? = null" in source
    assert "val typography: Typography = Typography()" in source


def test_a_theme_builder_export_becomes_the_colour_schemes(tmp_path: Path) -> None:
    colors = {
        "schemes": {
            "light": {"primary": "#00696e", "shadow": "#000000"},
            "dark": {"primary": "#4FD8E0", "surfaceContainer": "#1B2122"},
        }
    }
    project = load_project(_app(tmp_path, '[theme]\ncolors = "theme.json"\n', colors))
    source = render(project)
    assert "primary = Color(0xFF00696E)," in source
    assert "surfaceContainer = Color(0xFF1B2122)," in source
    # Theme Builder's shadow role has no ColorScheme counterpart.
    assert "shadow" not in source
    # Choosing colours turns the wallpaper's colours off unless asked for.
    assert "const val DYNAMIC: Boolean = false" in source
    assert plan(project).sources[PATH] == ["[theme]"]


def test_fonts_shapes_and_dark_mode_are_generated(tmp_path: Path) -> None:
    root = _app(
        tmp_path,
        '[theme]\ndark = "dark"\n[theme.fonts]\nbody = "inter"\n'
        "[theme.shapes]\nmedium = 20\n",
    )
    (root / "resources/fonts").mkdir(parents=True)
    (root / "resources/fonts/inter.ttf").write_bytes(b"font")
    source = render(load_project(root))
    assert "val darkMode: Boolean? = true" in source
    assert "private val bodyFont = FontFamily(Font(R.font.inter))" in source
    assert "bodyLarge = base.bodyLarge.copy(fontFamily = bodyFont)," in source
    assert "labelSmall = base.labelSmall.copy(fontFamily = bodyFont)," in source
    assert "titleLarge" not in source
    assert "medium = RoundedCornerShape(20.dp)," in source


@pytest.mark.parametrize(
    ("theme", "colors", "message"),
    [
        (
            '[theme]\ncolors = "theme.json"\n',
            {"schemes": {"light": {"primry": "#000000"}}},
            "unknown colour role",
        ),
        (
            '[theme]\ncolors = "theme.json"\n',
            {"schemes": {"light": {"primary": "red"}}},
            "#RRGGBB",
        ),
        ('[theme]\ncolors = "theme.json"\n', {"palettes": {}}, "no 'schemes'"),
        ('[theme]\ncolors = "missing.json"\n', None, "file is missing"),
        ('[theme]\ndark = "dim"\n', None, "system, light or dark"),
        ("[theme]\ndynamic = 1\n", None, "true or false"),
        ('[theme]\naccent = "#000000"\n', None, "unknown theme key"),
        ('[theme.fonts]\nbody = "inter"\n', None, "resources/fonts"),
        ('[theme.fonts]\nheading = "inter"\n', None, "unknown theme font slot"),
        ("[theme.shapes]\nhuge = 4\n", None, "unknown theme shape size"),
        ("[theme.shapes]\nsmall = 4.5\n", None, "corner radius"),
    ],
)
def test_an_invalid_theme_is_refused_by_name(
    tmp_path: Path, theme: str, colors: object, message: str
) -> None:
    with pytest.raises(ProjectError, match=message):
        render(load_project(_app(tmp_path, theme, colors)))


def test_the_notes_example_ships_a_valid_theme() -> None:
    source = render(load_project(NOTES))
    assert "onSurfaceVariant = Color(0xFF6C7779)," in source
    assert "onSurfaceVariant = Color(0xFF98A4A6)," in source
