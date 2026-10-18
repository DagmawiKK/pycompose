"""App dependency declarations through generated projects and CLI builds."""

import json
import tomllib
from pathlib import Path

import pytest
from test_cli_build import wrapper
from test_cli_init import NATIVE, cli

REQUIREMENTS_WRAPPER = """import os, zipfile
from pathlib import Path
text = os.environ["ORG_GRADLE_PROJECT_pycomposeRequirements"]
Path("requirements.txt.value").write_text(json.dumps(text.splitlines()))
output = Path("host/build/outputs/apk/debug/host-debug.apk")
output.parent.mkdir(parents=True)
with zipfile.ZipFile(output, "w") as archive:
    archive.writestr("AndroidManifest.xml", "fixture only")
"""


def build_with_requirements(project: Path, requirements: list[str]) -> None:
    config = project / "pycompose.toml"
    config.write_text(
        config.read_text().replace(
            "requirements = []", f"requirements = {json.dumps(requirements)}"
        )
    )
    wrapper(project, "import json\n" + REQUIREMENTS_WRAPPER)


def test_build_passes_requirements_as_data_without_editing_gradle(
    tmp_path: Path,
) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    requirements = [
        "requests[socks]==2.32.3",
        'numpy==1.26.2; python_version >= "3.12"',
    ]
    build_with_requirements(project, requirements)
    gradle = project / NATIVE / "host/build.gradle.kts"
    before = gradle.read_bytes()

    result = cli(project, "build")

    assert result.returncode == 0, result.stderr
    passed = json.loads((project / NATIVE / "requirements.txt.value").read_text())
    assert passed == requirements
    assert gradle.read_bytes() == before


def test_a_project_declaring_no_requirements_passes_none(tmp_path: Path) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    wrapper(project, "import json\n" + REQUIREMENTS_WRAPPER)

    result = cli(project, "build")

    assert result.returncode == 0, result.stderr
    assert json.loads((project / NATIVE / "requirements.txt.value").read_text()) == []


@pytest.mark.parametrize(
    "value",
    [
        '"numpy"',
        "123",
        '{name = "numpy"}',
        "[1]",
        "[true]",
        '[""]',
        '["   "]',
        '["numpy\\nrequests"]',
        '["numpy\\rrequests"]',
        '["numpy\\t"]',
    ],
)
def test_invalid_requirement_values_fail_before_gradle(
    tmp_path: Path, value: str
) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    config = project / "pycompose.toml"
    config.write_text(
        config.read_text().replace("requirements = []", f"requirements = {value}")
    )
    wrapper(project, 'from pathlib import Path\nPath("launched").touch()\n')

    result = cli(project, "build")

    assert result.returncode == 2
    assert "python.requirements" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (project / NATIVE / "launched").exists()


@pytest.mark.parametrize(
    "requirement",
    [
        "-r requirements.txt",
        "--extra-index-url=https://example.com",
        "./local-package",
        "../outside.whl",
        "/absolute/package.whl",
        "package-1.0-py3-none-any.whl",
        "https://example.com/package.whl",
        "package @ https://example.com/package.whl",
        "not a requirement",
    ],
)
def test_only_named_package_specifiers_are_accepted(
    tmp_path: Path, requirement: str
) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    config = project / "pycompose.toml"
    config.write_text(
        config.read_text().replace(
            "requirements = []", f"requirements = {json.dumps([requirement])}"
        )
    )
    wrapper(project, 'from pathlib import Path\nPath("launched").touch()\n')

    result = cli(project, "build")

    assert result.returncode == 2
    assert "python.requirements" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (project / NATIVE / "launched").exists()


def pin_template(project: Path, version: str | None) -> None:
    """Rewrite toolchain.template_version, or remove it when None."""
    config = project / "pycompose.toml"
    text = config.read_text()
    current = tomllib.loads(text)["toolchain"]["template_version"]
    if version is None:
        config.write_text(
            text.replace(f"template_version = {json.dumps(current)}\n", "")
        )
        return
    config.write_text(
        text.replace(
            f"template_version = {json.dumps(current)}",
            f"template_version = {json.dumps(version)}",
        )
    )


@pytest.mark.parametrize("version", ["0.3.0", None])
def test_requirements_need_a_scaffold_that_installs_them(
    tmp_path: Path, version: str | None
) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    build_with_requirements(project, ["numpy==1.26.2"])
    pin_template(project, version)

    result = cli(project, "build")

    assert result.returncode == 2
    assert "python.requirements" in result.stderr
    assert "0.4.0" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (project / NATIVE / "requirements.txt.value").exists()


def test_older_scaffolds_without_requirements_still_build(tmp_path: Path) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    wrapper(project, "import json\n" + REQUIREMENTS_WRAPPER)
    pin_template(project, "0.3.0")

    result = cli(project, "build")

    assert result.returncode == 0, result.stderr
    assert json.loads((project / NATIVE / "requirements.txt.value").read_text()) == []
