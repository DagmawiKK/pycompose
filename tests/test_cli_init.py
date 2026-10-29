"""Project creation through the public command-line seam."""

import json
import os
import subprocess
import sys
import tomllib
from importlib.resources import files
from pathlib import Path

import pytest

from pycompose.contract.catalog import SCHEMA_VERSION

NATIVE = Path(".pycompose/android")
OWNED = Path(".")
"""An app-owned (``--native``) project's Android root: a build never regenerates
it, so plumbing tests can stand a controlled wrapper in for Gradle."""


def cli(
    directory: Path, *arguments: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        **(env or {}),
        "PYTHONPATH": str(Path(__file__).parents[1]),
    }
    return subprocess.run(
        [sys.executable, "-m", "pycompose_cli", *arguments],
        cwd=directory,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_init_creates_config_python_entrypoint_and_resource_directories(
    tmp_path: Path,
) -> None:
    result = cli(tmp_path, "init", "demo")
    assert result.returncode == 0, result.stderr
    project = tmp_path / "demo"
    config = tomllib.loads((project / "pycompose.toml").read_text())
    assert config["app"] == {
        "name": "demo",
        "application_id": "com.example.app_demo",
        "version_name": "0.1.0",
        "version_code": 1,
    }
    assert config["python"] == {
        "entrypoint": "main:app",
        "source_dir": "app",
        "requirements": [],
    }
    assert config["resources"]["path"] == "resources"
    assert config["signing"]["store_password_env"] == "PYCOMPOSE_STORE_PASSWORD"
    assert config["signing"]["key_password_env"] == "PYCOMPOSE_KEY_PASSWORD"
    assert config["toolchain"]["schema_version"] == SCHEMA_VERSION
    for resource in ("assets", "drawables", "fonts"):
        assert (project / "resources" / resource).is_dir()
    assert json.loads((project / "resources" / "strings.json").read_text()) == {
        "app_name": "demo"
    }
    assert (project / "app" / "main.py").is_file()
    assert (project / ".gitignore").is_file()
    assert result.stderr == ""
    manifest = tomllib.loads(
        files("pycompose_cli")
        .joinpath("templates", "android", "template.toml")
        .read_text()
    )
    assert config["toolchain"]["template_version"] == manifest["template_version"]
    assert (project / NATIVE / "gradlew").stat().st_mode & 0o111
    assert (project / NATIVE / "gradle/wrapper/gradle-wrapper.jar").is_file()
    # init generates the sample's slice once, so the project works before its
    # first build and never ships the full catalog (ADR-0014).
    assert (project / "app" / "m3" / "generated_components.py").is_file()
    slice_root = ".pycompose/generated/ir/src/main/kotlin/com/pycompose/ir/generated"
    assert (project / NATIVE / slice_root / "UiModels.kt").is_file()


def test_reinit_warns_and_preserves_every_existing_file(tmp_path: Path) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    (project / "app" / "main.py").write_text("# user-owned replacement\n")
    (project / "pycompose.toml").write_text("# user-owned config\n")
    (project / "custom.txt").write_text("keep me\n")
    before = {
        file.relative_to(project): file.read_bytes()
        for file in project.rglob("*")
        if file.is_file()
    }
    result = cli(tmp_path, "init", "demo")
    assert result.returncode == 0
    assert "already exists" in result.stderr
    after = {
        file.relative_to(project): file.read_bytes()
        for file in project.rglob("*")
        if file.is_file()
    }
    assert after == before


@pytest.mark.parametrize(
    "name",
    [
        "",
        ".",
        "..",
        "../escape",
        "/absolute",
        "nested/demo",
        "9demo",
        "bad name",
        "x\nname",
        "a" * 64,
    ],
)
def test_invalid_names_fail_without_creating_any_paths(
    tmp_path: Path, name: str
) -> None:
    result = cli(tmp_path, "init", name)
    assert result.returncode == 2
    assert "name must" in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_existing_file_or_symlink_is_never_overwritten(tmp_path: Path) -> None:
    (tmp_path / "demo").write_bytes(b"user data")
    result = cli(tmp_path, "init", "demo")
    assert result.returncode == 2
    assert (tmp_path / "demo").read_bytes() == b"user data"
    (tmp_path / "link").symlink_to(tmp_path / "demo")
    assert cli(tmp_path, "init", "link").returncode == 2
    assert (tmp_path / "demo").read_bytes() == b"user data"


def test_existing_directory_symlink_warns_without_writing_into_target(
    tmp_path: Path,
) -> None:
    original = tmp_path / "original"
    original.mkdir()
    (tmp_path / "demo").symlink_to(original, target_is_directory=True)
    assert cli(tmp_path, "init", "demo").returncode == 0
    assert list(original.iterdir()) == []


@pytest.mark.parametrize(
    "command",
    [
        "init",
        "run",
        "build",
        "install",
        "debug",
        "release",
        "config",
        "sync",
        "doctor",
        "validate",
    ],
)
def test_command_entry_points_have_help(tmp_path: Path, command: str) -> None:
    result = cli(tmp_path, command, "--help")
    assert result.returncode == 0
    assert f"pycompose {command}" in result.stdout


@pytest.mark.parametrize(
    ("starter", "shown"),
    [
        ((), "Type your name and tap Greet."),
        (("--template", "viewmodel"), "Tapped 0 times"),
    ],
)
def test_generated_python_entrypoint_emits_valid_ir(
    tmp_path: Path, starter: tuple[str, ...], shown: str
) -> None:
    assert cli(tmp_path, "init", "demo-app", *starter).returncode == 0
    project = tmp_path / "demo-app"
    config = tomllib.loads((project / "pycompose.toml").read_text())
    assert config["app"]["application_id"] == "com.example.app_demo_app"
    script = (
        "from pycompose.bridge.session import compose_once\n"
        "snapshot, error = compose_once('main:app')\n"
        "assert snapshot, error\nprint(snapshot)"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project / "app",
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1])},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert f'"text":"{shown}"' in result.stdout
    assert not (project / "starters").exists()
