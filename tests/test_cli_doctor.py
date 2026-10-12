"""Toolchain diagnostics through controlled executables and environment paths."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_cli_init import cli


def executable(path: Path, output: str, exit_code: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"#!{sys.executable}\nprint({output!r})\nraise SystemExit({exit_code})\n"
    )
    path.chmod(0o755)


def test_doctor_reports_detected_tools_and_declared_plugin_versions(
    tmp_path: Path,
) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    (project / "gradle").mkdir(exist_ok=True)
    (project / "gradle" / "libs.versions.toml").write_text(
        '[versions]\nagp = "8.9.1"\nchaquopy = "17.0.0"\n'
    )
    executable(project / "gradlew", "Gradle fixture")
    sdk = tmp_path / "sdk"
    (sdk / "platforms" / "android-35").mkdir(parents=True)
    (sdk / "platforms" / "android-35" / "android.jar").write_bytes(b"platform fixture")
    executable(sdk / "build-tools" / "35.0.0" / "aapt2", "fixture")
    executable(
        sdk / "platform-tools" / "adb",
        "Android Debug Bridge version 1.0.41\nVersion 35.0.2",
    )
    jdk = tmp_path / "jdk"
    executable(jdk / "bin" / "java", 'openjdk version "17.0.13"')
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).parents[1]),
        "JAVA_HOME": str(jdk),
        "ANDROID_HOME": str(sdk),
        "ANDROID_SDK_ROOT": str(sdk),
    }
    result = subprocess.run(
        [sys.executable, "-m", "pycompose.cli", "doctor"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for expected in (
        "SDK:",
        "JDK: 17.0.13",
        "ADB:",
        "AGP (declared): 8.9.1",
        "Chaquopy (declared): 17.0.0",
        "Schema: 1.0.0",
    ):
        assert expected in result.stdout


def test_doctor_surfaces_a_broken_toolchain_instead_of_claiming_health(
    tmp_path: Path,
) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    (tmp_path / "demo" / "gradlew").unlink()
    (tmp_path / "demo" / "gradle" / "libs.versions.toml").unlink()
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).parents[1]),
        "JAVA_HOME": str(tmp_path / "missing-jdk"),
        "ANDROID_HOME": str(tmp_path / "missing-sdk"),
        "ANDROID_SDK_ROOT": str(tmp_path / "missing-sdk"),
        "PATH": "",
    }
    result = subprocess.run(
        [sys.executable, "-m", "pycompose.cli", "doctor"],
        cwd=tmp_path / "demo",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "FAIL SDK:" in result.stdout
    assert "FAIL JDK:" in result.stdout
    assert "FAIL ADB:" in result.stdout
    assert "FAIL Gradle wrapper:" in result.stdout
    assert "FAIL AGP" in result.stdout
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("version", ["1.8.0_402", "11.0.23", "1."])
def test_doctor_rejects_old_or_unparseable_jdk_versions(
    tmp_path: Path, version: str
) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    jdk = tmp_path / "jdk"
    executable(jdk / "bin" / "java", f'openjdk version "{version}"')
    result = cli(
        tmp_path / "demo",
        "doctor",
        env={
            "JAVA_HOME": str(jdk),
            "PATH": "",
            "ANDROID_HOME": str(tmp_path / "missing"),
            "ANDROID_SDK_ROOT": str(tmp_path / "missing"),
        },
    )
    assert result.returncode == 2
    assert "FAIL JDK:" in result.stdout
    assert "Traceback" not in result.stderr


def test_doctor_reports_schema_mismatch_and_unsupported_declared_plugins(
    tmp_path: Path,
) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    (project / "gradle").mkdir(exist_ok=True)
    (project / "gradle" / "libs.versions.toml").write_text(
        '[versions]\nagp = "invalid"\nchaquopy = "18.0.0"\n'
    )
    config = project / "pycompose.toml"
    config.write_text(
        config.read_text().replace(
            'schema_version = "1.0.0"', 'schema_version = "2.0.0"'
        )
    )
    result = cli(
        project,
        "doctor",
        env={
            "JAVA_HOME": str(tmp_path / "missing"),
            "PATH": "",
            "ANDROID_HOME": str(tmp_path / "missing"),
            "ANDROID_SDK_ROOT": str(tmp_path / "missing"),
        },
    )
    assert result.returncode == 2
    assert "FAIL AGP (declared)" in result.stdout
    assert "FAIL Chaquopy (declared)" in result.stdout
    assert "FAIL Schema:" in result.stdout


def test_doctor_outside_a_project_still_reports_system_checks(tmp_path: Path) -> None:
    result = cli(
        tmp_path,
        "doctor",
        env={
            "JAVA_HOME": str(tmp_path / "missing"),
            "PATH": "",
            "ANDROID_HOME": str(tmp_path / "missing"),
            "ANDROID_SDK_ROOT": str(tmp_path / "missing"),
        },
    )
    assert result.returncode == 2
    assert "SDK:" in result.stdout and "JDK:" in result.stdout
    assert "FAIL Schema:" in result.stdout
    assert "pycompose.toml" in result.stdout


def test_doctor_reports_unreadable_sdk_config_and_continues_other_checks(
    tmp_path: Path,
) -> None:
    (tmp_path / "local.properties").write_bytes(b"sdk.dir=\xff")
    result = cli(
        tmp_path,
        "doctor",
        env={
            "JAVA_HOME": str(tmp_path / "missing"),
            "PATH": "",
            "ANDROID_HOME": "",
            "ANDROID_SDK_ROOT": "",
        },
    )
    assert result.returncode == 2
    assert "FAIL SDK:" in result.stdout
    assert "FAIL JDK:" in result.stdout
    assert "FAIL Schema:" in result.stdout
    assert "Traceback" not in result.stderr
