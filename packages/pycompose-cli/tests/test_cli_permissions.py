"""Python requirements and Android permissions reach the build from the config."""

import json
from pathlib import Path

from pycompose_cli.project import ProjectError, load_project
from test_cli_build import wrapper
from test_cli_init import cli


def declare(project: Path, *, requirements: list[str], internet: bool) -> None:
    """Fill the requirements the init config declares, and ask for the network."""
    config = project / "pycompose.toml"
    text = config.read_text()
    assert text.count("requirements = []\n") == 1
    text = text.replace(
        "requirements = []\n", f"requirements = {json.dumps(requirements)}\n"
    )
    if internet:
        text += '\n[android]\npermissions = ["android.permission.INTERNET"]\n'
    config.write_text(text)


def test_requirements_and_permissions_reach_gradle_without_native_edits(
    tmp_path: Path,
) -> None:
    # An owned project's manifest is the app's; a generated one's is rewritten
    # with the permissions on every build (test_generated_project).
    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    project = tmp_path / "demo"
    declare(project, requirements=["httpx>=0.27,<0.29"], internet=True)
    source_manifest = project / "host/src/main/AndroidManifest.xml"
    original = source_manifest.read_bytes()
    wrapper(
        project,
        """import os, json, zipfile
from pathlib import Path
values = {key: value for key, value in os.environ.items()
          if key.startswith("ORG_GRADLE_PROJECT_pycompose")}
Path("build-inputs.json").write_text(json.dumps(values))
output = Path("host/build/outputs/apk/debug/host-debug.apk")
output.parent.mkdir(parents=True)
with zipfile.ZipFile(output, "w") as archive:
    archive.writestr("AndroidManifest.xml", "fixture only")
""",
    )

    result = cli(project, "build")

    assert result.returncode == 0, result.stderr
    inputs = json.loads((project / "build-inputs.json").read_text())
    assert inputs["ORG_GRADLE_PROJECT_pycomposeRequirements"] == "httpx>=0.27,<0.29"
    generated_manifest = Path(inputs["ORG_GRADLE_PROJECT_pycomposeManifest"])
    assert "android.permission.INTERNET" in generated_manifest.read_text()
    assert source_manifest.read_bytes() == original


def test_the_removed_extensions_table_names_its_replacement(tmp_path: Path) -> None:
    (tmp_path / "pycompose.toml").write_text(
        '[extensions]\ndefinitions = ["builtin:httpx"]\n'
    )
    try:
        load_project(tmp_path)
    except ProjectError as exc:
        assert "[python] requirements" in str(exc)
        assert "[android] permissions" in str(exc)
    else:
        raise AssertionError("an [extensions] table must be refused")
