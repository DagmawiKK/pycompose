"""Resource synchronization through CLI calls and observable project files."""

import json
from pathlib import Path
from xml.etree import ElementTree

import pytest
from test_cli_init import cli


def test_sync_translates_named_resources_and_is_byte_stable(tmp_path: Path) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    resources = project / "resources"
    (resources / "strings.json").write_text(json.dumps({"greeting": "Hello & <world>"}))
    (resources / "strings.fr.json").write_text(json.dumps({"greeting": "Bonjour"}))
    (resources / "drawables" / "hdpi").mkdir()
    (resources / "drawables" / "hdpi" / "logo.png").write_bytes(b"image bytes")
    (resources / "assets" / "nested").mkdir()
    (resources / "assets" / "nested" / "data.bin").write_bytes(b"asset bytes")
    (resources / "fonts" / "body.ttf").write_bytes(b"font bytes")
    result = cli(project, "sync")
    assert result.returncode == 0, result.stderr
    main = project / "host" / "src" / "main"
    assert (main / "res" / "drawable-hdpi" / "logo.png").read_bytes() == b"image bytes"
    assert (main / "assets" / "nested" / "data.bin").read_bytes() == b"asset bytes"
    assert (main / "res" / "font" / "body.ttf").read_bytes() == b"font bytes"
    strings = ElementTree.parse(main / "res" / "values" / "strings.xml").getroot()
    assert strings[0].attrib == {"name": "greeting", "formatted": "false"}
    assert strings[0].text == '"Hello & <world>"'
    french = ElementTree.parse(main / "res" / "values-fr" / "strings.xml").getroot()
    assert french[0].text == '"Bonjour"'
    before = {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }
    assert cli(project, "sync").returncode == 0
    assert cli(project, "sync", "--check").returncode == 0
    assert {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    } == before


def test_sync_refuses_unmanaged_outputs_and_never_clobbers_raw_res(
    tmp_path: Path,
) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    raw = project / "host" / "src" / "main" / "res" / "values"
    raw.mkdir(parents=True)
    (raw / "strings.xml").write_bytes(b"user strings")
    (raw / "colors.xml").write_bytes(b"user colors")
    result = cli(project, "sync")
    assert result.returncode == 2
    assert "unmanaged" in result.stderr
    assert (raw / "strings.xml").read_bytes() == b"user strings"
    assert (raw / "colors.xml").read_bytes() == b"user colors"


def test_check_detects_source_drift_without_modifying_the_project(
    tmp_path: Path,
) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    before = {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }
    assert cli(project, "sync", "--check").returncode == 1
    assert {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    } == before
    assert cli(project, "sync").returncode == 0
    assert cli(project, "sync", "--check").returncode == 0
    (project / "resources" / "strings.json").write_text('{"title":"new"}')
    result = cli(project, "sync", "--check")
    assert result.returncode == 1
    assert "strings.xml" in result.stdout


def test_sync_removes_only_unchanged_previously_generated_stale_files(
    tmp_path: Path,
) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    source = project / "resources" / "assets" / "old.bin"
    source.write_bytes(b"managed")
    assert cli(project, "sync").returncode == 0
    assets = project / "host" / "src" / "main" / "assets"
    (assets / "user.bin").write_bytes(b"user")
    source.unlink()
    assert cli(project, "sync", "--check").returncode == 1
    assert cli(project, "sync").returncode == 0
    assert not (assets / "old.bin").exists()
    assert (assets / "user.bin").read_bytes() == b"user"


def test_sync_refuses_locally_modified_generated_files_before_any_writes(
    tmp_path: Path,
) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    source = project / "resources" / "assets" / "old.bin"
    source.write_bytes(b"managed")
    assert cli(project, "sync").returncode == 0
    destination = project / "host" / "src" / "main" / "assets" / "old.bin"
    destination.write_bytes(b"user edited")
    source.unlink()
    (project / "resources" / "strings.json").write_text('{"title":"new"}')
    before = {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }
    result = cli(project, "sync")
    assert result.returncode == 2
    assert "modified" in result.stderr
    assert {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    } == before


@pytest.mark.parametrize(
    "locale,folder",
    [
        ("en", "values-en"),
        ("en-US", "values-en-rUS"),
        ("en_US", "values-en-rUS"),
        ("zh-Hans-CN", "values-b+zh+Hans+CN"),
        ("es-419", "values-b+es+419"),
    ],
)
def test_locale_strings_preserve_android_literal_escaping(
    tmp_path: Path, locale: str, folder: str
) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    (project / "resources" / f"strings.{locale}.json").write_text(
        json.dumps({"title": '  It\'s "quoted" \\ @ref ?attr\nnext\t100%  '})
    )
    assert cli(project, "sync").returncode == 0
    text = (
        ElementTree.parse(
            project / "host" / "src" / "main" / "res" / folder / "strings.xml"
        )
        .getroot()[0]
        .text
    )
    assert text == '"  It\'s \\"quoted\\" \\\\ \\@ref \\?attr\\nnext\\t100%  "'


@pytest.mark.parametrize(
    "filename,content",
    [
        ("strings.json", '{"BadName":"bad"}'),
        ("strings.json", '{"title":1}'),
        ("strings.json", '{"title":"a","title":"b"}'),
        ("strings.json", '{"title":"\\u0000"}'),
        ("strings.json", '{"title":"\\ud800"}'),
        ("strings.json", "[]"),
        ("strings.json", '{"title":NaN}'),
        ("strings.bad-locale.json", '{"title":"bad"}'),
        ("drawables/BadName.png", "bytes"),
        ("drawables/unknown/logo.png", "bytes"),
        ("fonts/body.woff", "bytes"),
    ],
)
def test_invalid_resources_fail_before_generating_outputs(
    tmp_path: Path, filename: str, content: str
) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    source = project / "resources" / filename
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(content)
    result = cli(project, "sync")
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert not (
        project / "host" / "src" / "main" / "res" / "values" / "strings.xml"
    ).exists()


def test_duplicate_drawable_names_and_locale_aliases_are_rejected(
    tmp_path: Path,
) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    (project / "resources" / "drawables" / "logo.xml").write_bytes(b"vector")
    (project / "resources" / "drawables" / "logo.png").write_bytes(b"raster")
    assert cli(project, "sync").returncode == 2
    (project / "resources" / "drawables" / "logo.png").unlink()
    (project / "resources" / "strings.en_US.json").write_text("{}")
    (project / "resources" / "strings.en-US.json").write_text("{}")
    assert cli(project, "sync").returncode == 2


def test_symlinked_source_and_output_paths_are_never_followed(tmp_path: Path) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"keep")
    link = project / "resources" / "assets" / "link.txt"
    link.symlink_to(outside)
    assert cli(project, "sync").returncode == 2
    link.unlink()
    (project / "host").rename(project / "original_host")
    (project / "host").symlink_to(tmp_path)
    assert cli(project, "sync").returncode == 2
    assert outside.read_bytes() == b"keep"


def test_modified_active_outputs_are_not_overwritten_and_manifest_paths_cannot_escape(
    tmp_path: Path,
) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    assert cli(project, "sync").returncode == 0
    strings = project / "host" / "src" / "main" / "res" / "values" / "strings.xml"
    strings.write_bytes(b"user edit")
    assert cli(project, "sync").returncode == 2
    assert strings.read_bytes() == b"user edit"
    (project / ".pycompose" / "resource-sync.json").write_text(
        json.dumps(
            {
                "version": 1,
                "files": {"host/src/main/res/../../../../outside.txt": "0" * 64},
            }
        )
    )
    assert cli(project, "sync").returncode == 2


def test_configured_resource_path_is_used_and_confined_to_project(
    tmp_path: Path,
) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    (project / "resources").rename(project / "media")
    config = project / "pycompose.toml"
    config.write_text(
        config.read_text().replace('path = "resources"', 'path = "media"')
    )
    assert cli(project, "sync").returncode == 0
    config.write_text(config.read_text().replace('path = "media"', 'path = "../media"'))
    assert cli(project, "sync").returncode == 2
