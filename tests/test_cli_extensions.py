"""Extension discovery and admission through the public project CLI."""

import json
import re
from pathlib import Path

import pytest
from test_cli_build import wrapper
from test_cli_init import cli


def test_external_definition_plans_without_importing_its_implementation(
    tmp_path: Path,
) -> None:
    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    project = tmp_path / "demo"
    (project / "app" / "dangerous.py").write_text("raise RuntimeError('imported')\n")
    (project / "custom.toml").write_text(
        'format = 1\nid = "example.custom"\nversion = "1.0.0"\n'
        'interface = 1\nrequirements = ["some-library>=1"]\n'
        'modules = []\nscenarios = ["example.roundtrip"]\n'
        '[requires]\n"python.serial" = 1\n'
        '[optional]\n"android.camera" = 1\n'
    )
    with (project / "pycompose.toml").open("a") as stream:
        stream.write('\n[extensions]\ndefinitions = ["custom.toml"]\n')

    result = cli(project, "extensions", "plan")

    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan["extensions"] == ["example.custom"]
    assert plan["requirements"] == ["some-library>=1"]
    assert plan["missingOptional"] == ["example.custom -> android.camera@1"]
    assert plan["evidence"] == "unverified"
    assert plan["errors"] == []


def select(project: Path, definitions: list[str], *, internet: bool = False) -> None:
    with (project / "pycompose.toml").open("a") as stream:
        stream.write(f"\n[extensions]\ndefinitions = {json.dumps(definitions)}\n")
        if internet:
            stream.write('\n[android]\npermissions = ["android.permission.INTERNET"]\n')


def test_reference_extensions_use_generic_build_selection_without_native_edits(
    tmp_path: Path,
) -> None:
    # An owned project's manifest is the app's; a generated one's is rewritten
    # with the permissions on every build (test_generated_project).
    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    project = tmp_path / "demo"
    select(project, ["builtin:httpx", "builtin:sqlite"], internet=True)
    native_root = project
    source_manifest = native_root / "host/src/main/AndroidManifest.xml"
    original = source_manifest.read_bytes()
    wrapper(
        project,
        """import os, json, zipfile
from pathlib import Path
values = {key: value for key, value in os.environ.items()
          if key.startswith("ORG_GRADLE_PROJECT_pycompose")}
Path("extension-inputs.json").write_text(json.dumps(values))
output = Path("host/build/outputs/apk/debug/host-debug.apk")
output.parent.mkdir(parents=True)
with zipfile.ZipFile(output, "w") as archive:
    archive.writestr("AndroidManifest.xml", "fixture only")
""",
    )

    result = cli(project, "build")

    assert result.returncode == 0, result.stderr
    inputs = json.loads((native_root / "extension-inputs.json").read_text())
    assert inputs["ORG_GRADLE_PROJECT_pycomposeRequirements"] == "httpx>=0.27,<0.29"
    assert inputs["ORG_GRADLE_PROJECT_pycomposeIntegrationModules"].splitlines() == [
        "httpx",
        "sqlite",
    ]
    generated_manifest = Path(inputs["ORG_GRADLE_PROJECT_pycomposeManifest"])
    assert "android.permission.INTERNET" in generated_manifest.read_text()
    assert source_manifest.read_bytes() == original


def test_missing_required_capability_stops_before_build_output_changes(
    tmp_path: Path,
) -> None:
    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    project = tmp_path / "demo"
    select(project, ["builtin:httpx"])
    wrapper(project, 'from pathlib import Path\nPath("launched").touch()\n')
    before = {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}

    result = cli(project, "build")

    assert result.returncode == 2
    assert "pycompose.httpx -> android.internet@1" in result.stderr
    assert all(path.read_bytes() == data for path, data in before.items())
    assert not (project / ".pycompose/android/launched").exists()


@pytest.mark.parametrize(
    "declaration",
    [
        'definitions = ["../outside.toml"]',
        'definitions = ["builtin:../sqlite"]',
        'definitions = ["builtin:sqlite", "builtin:sqlite"]',
        'definitions = "builtin:sqlite"',
    ],
)
def test_invalid_selection_fails_without_imports_or_tracebacks(
    tmp_path: Path,
    declaration: str,
) -> None:
    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    project = tmp_path / "demo"
    with (project / "pycompose.toml").open("a") as stream:
        stream.write(f"\n[extensions]\n{declaration}\n")
    result = cli(project, "extensions", "plan")
    assert result.returncode == 2
    assert "Traceback" not in result.stderr


def test_target_restrictions_are_not_desktop_import_success(tmp_path: Path) -> None:
    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    project = tmp_path / "demo"
    (project / "native.toml").write_text(
        'format = 1\ninterface = 1\nid = "example.native"\nversion = "1.0.0"\n'
        'python_versions = ["3.11"]\nabis = ["arm64-v8a"]\nmin_sdk = 28\n'
    )
    select(project, ["native.toml"])
    result = cli(project, "extensions", "plan")
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["errors"] == [
        "example.native -> Python 3.12 not declared",
        "example.native -> ABI x86_64 not declared",
        "example.native -> needs minSdk 28 (host floor 24)",
    ]
    assert report["evidence"] == "unverified"


def test_plan_reports_missing_host_runtime_before_build(tmp_path: Path) -> None:
    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    project = tmp_path / "demo"
    config = project / "pycompose.toml"
    config.write_text(
        re.sub(
            r'template_version = "[^"]+"',
            'template_version = "0.6.0"',
            config.read_text(),
            count=1,
        )
    )
    select(project, ["builtin:sqlite"])
    result = cli(project, "extensions", "plan")
    assert result.returncode == 2, result.stdout
    report = json.loads(result.stdout)
    assert any("template_version 0.7.0" in error for error in report["errors"])
    assert report["checks"]["capabilities"] == "failed"
