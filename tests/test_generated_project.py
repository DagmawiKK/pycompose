"""The Android project is generated from the app on every build (plan 31 §21)."""

from __future__ import annotations

import shutil
import tarfile
from pathlib import Path

import pytest

from pycompose.cli import toolchain
from pycompose.cli.icons import icon_files
from pycompose.cli.init import init_project
from pycompose.cli.migrate import migrate
from pycompose.cli.prebuild import GENERATED, explain, generated, plan, prebuild
from pycompose.cli.project import ProjectError, load_project

ROOT = Path(__file__).resolve().parents[1]
NOTES = ROOT / "examples/notes"
RES = ".pycompose/android/host/src/main/res"


def _notes(tmp_path: Path) -> Path:
    target = tmp_path / "notes"
    shutil.copytree(NOTES, target, ignore=shutil.ignore_patterns(".pycompose"))
    return target


def test_the_notes_icon_is_one_svg(tmp_path: Path) -> None:
    files = icon_files(load_project(_notes(tmp_path)))
    foreground = files["host/src/main/res/drawable/app_icon_foreground.xml"].decode()
    assert 'android:fillType="evenOdd"' in foreground
    assert 'android:fillColor="#FBF9F7"' in foreground
    background = files["host/src/main/res/drawable/app_icon_background.xml"].decode()
    assert "#00696E" in background
    # Themed icons tint the monochrome layer, so its paint is plain white.
    assert (
        "#FFFFFF"
        in files["host/src/main/res/drawable/app_icon_monochrome.xml"].decode()
    )
    assert (
        "app_icon_monochrome"
        in files["host/src/main/res/drawable-v26/app_icon.xml"].decode()
    )


def test_an_svg_feature_the_converter_does_not_draw_is_refused(tmp_path: Path) -> None:
    project = _notes(tmp_path)
    (project / "icon.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 108 108">'
        '<path transform="scale(2)" d="M0,0h1v1z"/></svg>'
    )
    with pytest.raises(ProjectError, match="does not draw"):
        icon_files(load_project(project))


def test_generation_is_deterministic_and_owns_only_its_files(tmp_path: Path) -> None:
    root = _notes(tmp_path)
    project = load_project(root)
    assert generated(project)
    assert plan(project).files == plan(project).files
    assert prebuild(project)
    assert prebuild(project) == []
    android = root / GENERATED
    (android / "host/build").mkdir(parents=True)
    (android / "host/build/output.txt").write_text("kept")
    (root / "icon.svg").unlink()
    (root / "pycompose.toml").write_text(
        (root / "pycompose.toml").read_text().replace('icon = "icon.svg"\n', "")
    )
    changed = prebuild(load_project(root))
    # The icon's own monochrome layer goes; the template's icon comes back.
    assert "host/src/main/res/drawable/app_icon_monochrome.xml" in changed
    assert not (android / "host/src/main/res/drawable/app_icon_monochrome.xml").exists()
    assert (android / "host/build/output.txt").read_text() == "kept"
    assert explain(load_project(root), "host/src/main/res/drawable/app_icon.xml")[
        0
    ].startswith("template ")


def test_fragments_merge_and_never_replace_generated_files(tmp_path: Path) -> None:
    root = _notes(tmp_path)
    (root / "android").mkdir()
    (root / "android/manifest.xml").write_text("<manifest />\n")
    overlay = root / "resources/android/res/xml"
    overlay.mkdir(parents=True)
    (overlay / "shortcuts.xml").write_text("<shortcuts />\n")
    generation = plan(load_project(root))
    assert "fragments/build.gradle.kts" in generation.files
    assert generation.sources["host/src/main/res/xml/shortcuts.xml"] == [
        "resources/android/res"
    ]
    clash = root / "resources/android/res/drawable"
    clash.mkdir()
    (clash / "app_icon.xml").write_text("<vector />\n")
    with pytest.raises(ProjectError, match="cannot replace a generated file"):
        plan(load_project(root))


def test_init_generates_the_android_project(tmp_path: Path) -> None:
    root, created, _ = init_project("demo", directory=tmp_path)
    assert created
    assert (root / GENERATED / "settings.gradle.kts").is_file()
    assert "!.pycompose/android/" not in (root / ".gitignore").read_text()
    assert not (root / "host").exists()


def test_migrate_turns_an_owned_project_into_a_generated_one(tmp_path: Path) -> None:
    root, _, _ = init_project("owned", directory=tmp_path, native=True)
    res = root / "host/src/main/res"
    # The notes app's old hand-written icon: the vectors its overlay used to carry.
    icons = icon_files(load_project(_notes(tmp_path)))
    for path, content in icons.items():
        if "monochrome" not in path:
            target = res / path.removeprefix("host/src/main/res/")
            target.write_bytes(content.split(b"-->\n", 1)[1])
    (res / "xml").mkdir(exist_ok=True)
    (res / "xml/extra.xml").write_text("<extra />\n")
    found = migrate(load_project(root))
    assert found.refused == []
    assert "#00696E" in (root / "pycompose.toml").read_text()
    assert 'fill-rule="evenodd"' in (root / "icon.svg").read_text()
    assert (root / "resources/android/res/xml/extra.xml").is_file()
    assert not (root / "host").exists()
    assert (root / RES / "drawable/app_icon_foreground.xml").is_file()


def test_migrate_refuses_an_edited_template_file_and_changes_nothing(
    tmp_path: Path,
) -> None:
    root, _, _ = init_project("edited", directory=tmp_path, native=True)
    build = root / "host/build.gradle.kts"
    build.write_text(build.read_text() + "\n// mine\n")
    found = migrate(load_project(root))
    assert found.refused == [
        "host/build.gradle.kts: differs from the template; it has no key"
    ]
    assert build.is_file()
    assert 'android_dir = "."' in (root / "pycompose.toml").read_text()


def test_the_toolchain_is_read_from_the_template_and_the_lock() -> None:
    pinned = toolchain.lock()
    assert pinned.compile_sdk == 37
    assert pinned.min_sdk == 24
    assert pinned.gradle and len(pinned.gradle_sha256) == 64
    for archive in pinned.locked["jdk"]["archives"].values():
        assert len(archive["sha256"]) == 64


def test_an_archive_member_escaping_its_directory_is_refused(tmp_path: Path) -> None:
    archive = tmp_path / "bad.tar.gz"
    payload = tmp_path / "payload"
    payload.write_text("x")
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(payload, arcname="../escape")
    with pytest.raises(ProjectError, match="escapes"):
        toolchain.unpack(archive, tmp_path / "out")


def test_the_apps_permissions_are_written_into_the_generated_manifest(
    tmp_path: Path,
) -> None:
    root = _notes(tmp_path)
    config = root / "pycompose.toml"
    config.write_text(
        config.read_text()
        + '\n[android]\npermissions = ["android.permission.INTERNET"]\n'
    )
    generation = plan(load_project(root))
    manifest = generation.files["host/src/main/AndroidManifest.xml"].decode()
    assert 'android:name="android.permission.INTERNET"' in manifest
    assert (
        "[android] permissions"
        in generation.sources["host/src/main/AndroidManifest.xml"]
    )


def test_build_plugins_add_typed_changes_in_their_declared_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from pycompose.cli import plugins

    def camera(model: plugins.AndroidModel) -> plugins.AndroidModel:
        return replace(model, features={"android.hardware.camera": False})

    def maps(model: plugins.AndroidModel) -> plugins.AndroidModel:
        return replace(model, meta_data={"com.example.key": "${MAPS_KEY}"})

    class Point:
        def __init__(self, name: str, function: plugins.Plugin) -> None:
            self.name, self.load = name, lambda: function

    monkeypatch.setattr(
        plugins,
        "entry_points",
        lambda group: [Point("camera", camera), Point("maps", maps)]
        * (group == plugins.GROUP),
    )
    root = _notes(tmp_path)
    config = root / "pycompose.toml"
    config.write_text(
        config.read_text() + '\n[android]\nplugins = ["camera", "maps"]\n'
    )
    manifest = (
        plan(load_project(root)).files["host/src/main/AndroidManifest.xml"].decode()
    )
    assert 'android:name="android.hardware.camera" android:required="false"' in manifest
    assert 'android:name="com.example.key"' in manifest
    config.write_text(config.read_text().replace('"maps"]', '"missing"]'))
    with pytest.raises(ProjectError, match="not installed"):
        plan(load_project(root))
