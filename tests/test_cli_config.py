"""App identity through the config command, not hand-edited files."""

import json
import tomllib
from pathlib import Path

import pytest
from test_cli_build import wrapper
from test_cli_init import cli


def test_config_show_prints_every_setting_and_its_source(tmp_path: Path) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    result = cli(tmp_path / "demo", "config", "show")
    assert result.returncode == 0, result.stderr
    for expected in (
        "label",
        "application_id",
        "com.example.app_demo",
        "version_name",
        "0.1.0",
        "version_code",
        "resources/strings.json",
        "pycompose.toml",
    ):
        assert expected in result.stdout


def test_config_without_arguments_lists_settings_and_a_hint(tmp_path: Path) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    result = cli(tmp_path / "demo", "config")
    assert result.returncode == 0, result.stderr
    assert "resources/strings.json" in result.stdout
    assert "config set" in result.stdout


def test_label_change_rewrites_only_the_string(tmp_path: Path) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    strings = project / "resources" / "strings.json"
    strings.write_text('{\n  "other": "kept",\n  "app_name": "demo"\n}\n')
    result = cli(project, "config", "set", "label", "Notes [beta]")
    assert result.returncode == 0, result.stderr
    assert strings.read_text() == (
        '{\n  "other": "kept",\n  "app_name": "Notes [beta]"\n}\n'
    )


def test_label_change_adds_app_name_when_the_file_lacks_it(tmp_path: Path) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    strings = project / "resources" / "strings.json"
    strings.write_text('{"greeting": "hi"}\n')
    assert cli(project, "config", "set", "label", "Notes").returncode == 0
    assert json.loads(strings.read_text()) == {"greeting": "hi", "app_name": "Notes"}


def test_identity_and_version_changes_keep_the_rest_of_the_toml(tmp_path: Path) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    config = project / "pycompose.toml"
    before = tomllib.loads(config.read_text())
    for key, value in (
        ("application_id", "com.acme.notes"),
        ("version_name", "1.4.0"),
        ("version_code", "12"),
    ):
        assert cli(project, "config", "set", key, value).returncode == 0
    after = tomllib.loads(config.read_text())
    assert after["app"] == {
        "name": "demo",
        "application_id": "com.acme.notes",
        "version_name": "1.4.0",
        "version_code": 12,
    }
    assert after["toolchain"] == before["toolchain"]
    assert after["signing"] == before["signing"]


def test_configured_version_reaches_the_gradle_invocation(tmp_path: Path) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    assert cli(project, "config", "set", "version_name", "2.0.0").returncode == 0
    assert cli(project, "config", "set", "version_code", "7").returncode == 0
    wrapper(
        project,
        """import os, zipfile
from pathlib import Path
assert os.environ["ORG_GRADLE_PROJECT_pycomposeVersionName"] == "2.0.0"
assert os.environ["ORG_GRADLE_PROJECT_pycomposeVersionCode"] == "7"
output = Path("host/build/outputs/apk/debug/host-debug.apk")
output.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(output, "w") as archive:
    archive.writestr("AndroidManifest.xml", "fixture only")
""",
    )
    assert cli(project, "build").returncode == 0


@pytest.mark.parametrize(
    "key,value,message",
    [
        ("application_id", "not a package", "application_id"),
        ("application_id", "com.acme.", "application_id"),
        ("version_name", "", "version_name"),
        ("version_code", "zero", "version_code"),
        ("version_code", "0", "version_code"),
        ("label", "", "label"),
        ("labell", "x", "unknown setting"),
    ],
)
def test_config_rejects_invalid_settings(
    tmp_path: Path, key: str, value: str, message: str
) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    result = cli(tmp_path / "demo", "config", "set", key, value)
    assert result.returncode == 2
    assert message in result.stderr
    assert "Traceback" not in result.stderr


def test_config_set_without_a_value_is_actionable(tmp_path: Path) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    result = cli(tmp_path / "demo", "config", "set", "label")
    assert result.returncode == 2
    assert "config set takes" in result.stderr
