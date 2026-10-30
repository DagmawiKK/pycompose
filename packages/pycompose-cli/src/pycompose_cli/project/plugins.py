"""Build plugins: the typed escape hatch past config keys.

A plugin is a function an installed package exposes under the
``pycompose.build_plugins`` entry point group and an app names in
``[android] plugins``. It receives the project's Android additions as data --
hardware features, intent queries, application metadata, extra resources --
and returns them changed; it never edits text. Plugins run in the order the app
lists them, so the same inputs always generate the same project.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from types import MappingProxyType

from pycompose_cli.project import Project, ProjectError

GROUP = "pycompose.build_plugins"
_ANDROID = 'xmlns:android="http://schemas.android.com/apk/res/android"'


@dataclass(frozen=True)
class AndroidModel:
    """What a plugin may add to the generated project.

    Attributes:
        features: ``uses-feature`` names, each with whether it is required.
        queries: Intent actions the app looks up (package visibility).
        meta_data: ``meta-data`` entries of the application, by name.
        resources: Extra resource files, by path below ``res/``.
    """

    features: Mapping[str, bool] = field(default_factory=lambda: MappingProxyType({}))
    queries: tuple[str, ...] = ()
    meta_data: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    resources: Mapping[str, bytes] = field(default_factory=lambda: MappingProxyType({}))


Plugin = Callable[[AndroidModel], AndroidModel]


def run_plugins(project: Project) -> AndroidModel:
    """Run the app's plugins, in the order it lists them.

    Args:
        project: The app.

    Returns:
        The additions every plugin made.

    Raises:
        ProjectError: If a named plugin is not installed or returns no model.
    """
    names = project.table("android").get("plugins", [])
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise ProjectError("android.plugins must be an array of plugin names")
    installed = {point.name: point for point in entry_points(group=GROUP)}
    model = AndroidModel()
    for name in names:
        if name not in installed:
            raise ProjectError("build plugin is not installed", plugin=name)
        plugin: Plugin = installed[name].load()
        model = plugin(model)
        if not isinstance(model, AndroidModel):
            raise ProjectError("build plugin returned no model", plugin=name)
    return model


def manifest_with(manifest: str, model: AndroidModel) -> str:
    """The manifest declaring a model's features, queries and metadata.

    Args:
        manifest: The generated manifest.
        model: The plugins' additions.

    Returns:
        The manifest with them merged in.
    """
    top = "".join(
        f'    <uses-feature {_ANDROID} android:name="{name}" '
        f'android:required="{str(required).lower()}" />\n'
        for name, required in sorted(model.features.items())
    )
    if model.queries:
        intents = "".join(
            f'        <intent><action android:name="{action}" /></intent>\n'
            for action in sorted(set(model.queries))
        )
        top += f"    <queries {_ANDROID}>\n{intents}    </queries>\n"
    inner = "".join(
        f'        <meta-data {_ANDROID} android:name="{name}" '
        f'android:value="{value}" />\n'
        for name, value in sorted(model.meta_data.items())
    )
    return _before(_before(manifest, "</application>", inner), "</manifest>", top)


def _before(text: str, closing: str, lines: str) -> str:
    """Insert whole lines before the line holding a closing tag."""
    at = text.find(closing)
    if not lines or at < 0:
        return text
    start = text.rfind("\n", 0, at) + 1
    return text[:start] + lines + text[start:]
