"""Gradle orchestration through a controlled wrapper executable, not an APK build."""

import json
import sys
import tomllib
from pathlib import Path

import pytest
from test_cli_init import OWNED, cli

from pycompose.model.catalog.lock import SCHEMA_VERSION


def wrapper(project: Path, body: str) -> None:
    config = project / "pycompose.toml"
    if config.is_file():
        project = project / tomllib.loads(config.read_text())["toolchain"].get(
            "android_dir", "."
        )
    (project / "settings.gradle.kts").write_text('include(":host")\n')
    script = project / "gradlew"
    script.write_text(f"#!{sys.executable}\n" + body)
    script.chmod(0o755)


@pytest.mark.parametrize(
    "arguments,task,kind,variant",
    [
        ((), ":host:assembleDebug", "apk", "debug"),
        (("aab",), ":host:bundleDebug", "bundle", "debug"),
    ],
)
def test_build_syncs_resources_invokes_gradle_and_reports_output(
    tmp_path: Path, arguments: tuple[str, ...], task: str, kind: str, variant: str
) -> None:
    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    project = tmp_path / "demo"
    wrapper(
        project,
        """import json, os, sys, zipfile
from pathlib import Path
assert os.environ["ORG_GRADLE_PROJECT_pycomposeApplicationId"] == "com.example.app_demo"
assert os.environ["ORG_GRADLE_PROJECT_pycomposeVersionCode"] == "1"
assert os.environ["ORG_GRADLE_PROJECT_pycomposeVersionName"] == "0.1.0"
assert os.environ["ORG_GRADLE_PROJECT_pycomposeEntrypoint"] == "main:app"
source = Path(os.environ["ORG_GRADLE_PROJECT_pycomposeSourceDir"])
assert source == Path("app").resolve()
# The blocks starter draws with the library's components, so it carries them.
assert os.environ["ORG_GRADLE_PROJECT_pycomposeOwnSlice"] == "false"
runtime = Path(os.environ["ORG_GRADLE_PROJECT_pycomposeRuntimeDir"])
assert (runtime / "pycompose/host/bridge/runtime.py").is_file()
assert Path(os.environ["ORG_GRADLE_PROJECT_pycomposeBuildPython"]).is_file()
assert Path("host/src/main/res/values/strings.xml").is_file()
Path("invocation.json").write_text(json.dumps(sys.argv[1:]))
kind = "bundle" if "bundle" in sys.argv[1] else "apk"
extension = "aab" if kind == "bundle" else "apk"
output = Path(f"host/build/outputs/{kind}/debug/host-debug.{extension}")
output.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(output, "w") as archive:
    name = ("AndroidManifest.xml" if kind == "apk"
            else "base/manifest/AndroidManifest.xml")
    archive.writestr(name, "fixture only")
    if kind == "bundle": archive.writestr("BundleConfig.pb", "fixture only")
""",
    )
    result = cli(project, "build", *arguments)
    assert result.returncode == 0, result.stderr
    assert json.loads((project / OWNED / "invocation.json").read_text())[0] == task
    assert f"host/build/outputs/{kind}/{variant}/host-debug." in result.stdout


def test_build_reports_the_deferred_android_scaffold(tmp_path: Path) -> None:
    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    (tmp_path / "demo" / OWNED / "gradlew").unlink()
    result = cli(tmp_path / "demo", "build")
    assert result.returncode == 2
    assert "Android scaffold" in result.stderr


@pytest.mark.parametrize(
    "kind,task,folder",
    [("apk", ":host:assembleRelease", "apk"), ("aab", ":host:bundleRelease", "bundle")],
)
def test_release_signing_uses_env_not_argv_or_persistent_files(
    tmp_path: Path, kind: str, task: str, folder: str
) -> None:
    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    project = tmp_path / "demo"
    key = tmp_path / "external key.jks"
    key.write_bytes(b"keystore fixture")
    config = project / "pycompose.toml"
    config.write_text(
        config.read_text()
        .replace('keystore = ""', f"keystore = {json.dumps(str(key))}")
        .replace('key_alias = ""', 'key_alias = "release"')
    )
    wrapper(
        project,
        """import json, os, sys, zipfile
from pathlib import Path
prefix = "ORG_GRADLE_PROJECT_android.injected.signing."
assert Path(os.environ[prefix + "store.file"]).is_file()
assert os.environ[prefix + "key.alias"] == "release"
assert os.environ[prefix + "store.password"] == os.environ["PYCOMPOSE_STORE_PASSWORD"]
assert os.environ[prefix + "key.password"] == os.environ["PYCOMPOSE_KEY_PASSWORD"]
print(os.environ[prefix + "store.password"])
print(os.environ[prefix + "key.password"], file=sys.stderr)
Path("invocation.json").write_text(json.dumps(sys.argv[1:]))
kind = "bundle" if "bundle" in sys.argv[1] else "apk"
extension = "aab" if kind == "bundle" else "apk"
output = Path(f"host/build/outputs/{kind}/release/host-release.{extension}")
output.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(output, "w") as archive:
    name = ("AndroidManifest.xml" if kind == "apk"
            else "base/manifest/AndroidManifest.xml")
    archive.writestr(name, "fixture only")
    if kind == "bundle": archive.writestr("BundleConfig.pb", "fixture only")
""",
    )
    secrets = {
        "PYCOMPOSE_STORE_PASSWORD": "store-secret;$(touch unexpected)",
        "PYCOMPOSE_KEY_PASSWORD": "key-secret",
    }
    result = cli(project, "build", kind, "--release", env=secrets)
    assert result.returncode == 0, result.stderr
    assert task == json.loads((project / OWNED / "invocation.json").read_text())[0]
    assert f"outputs/{folder}/release/host-release.{kind}" in result.stdout
    assert "[REDACTED]" in result.stdout and "[REDACTED]" in result.stderr
    assert not (project / "unexpected").exists()
    for secret in secrets.values():
        assert secret not in result.stdout + result.stderr
        assert secret not in (project / OWNED / "invocation.json").read_text()
        assert secret not in config.read_text()


def test_release_missing_signing_configuration_does_not_launch_gradle(
    tmp_path: Path,
) -> None:
    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    project = tmp_path / "demo"
    wrapper(project, 'from pathlib import Path\nPath("launched").touch()\n')
    result = cli(project, "build", "apk", "--release")
    assert result.returncode == 2
    assert "signing.keystore" in result.stderr
    assert not (project / OWNED / "launched").exists()


@pytest.mark.parametrize(
    "body,message",
    [
        (
            'import sys\nprint("compile failed", file=sys.stderr)\n'
            "raise SystemExit(7)\n",
            "Gradle task failed",
        ),
        ("pass\n", "produced no artifact"),
        (
            "from pathlib import Path\n"
            'p = Path("host/build/outputs/apk/debug/bad.apk")\n'
            'p.parent.mkdir(parents=True)\np.write_bytes(b"not an apk")\n',
            "not a valid ZIP",
        ),
        (
            "import zipfile\nfrom pathlib import Path\n"
            'p = Path("host/build/outputs/apk/debug/empty.apk")\n'
            'p.parent.mkdir(parents=True)\nzipfile.ZipFile(p, "w").close()\n',
            "not an Android artifact",
        ),
    ],
)
def test_gradle_failure_or_missing_invalid_output_never_claims_success(
    tmp_path: Path, body: str, message: str
) -> None:
    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    project = tmp_path / "demo"
    wrapper(project, body)
    result = cli(project, "build")
    assert result.returncode == 2
    assert message in result.stderr
    assert "Built artifact" not in result.stdout
    assert "Traceback" not in result.stderr


def test_build_rejects_schema_mismatch_and_resource_conflicts_before_gradle(
    tmp_path: Path,
) -> None:
    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    project = tmp_path / "demo"
    wrapper(project, 'from pathlib import Path\nPath("launched").touch()\n')
    config = project / "pycompose.toml"
    original = config.read_text()
    config.write_text(
        original.replace(
            f'schema_version = "{SCHEMA_VERSION}"', 'schema_version = "2.0.0"'
        )
    )
    assert cli(project, "build").returncode == 2
    config.write_text(original)
    raw = project / OWNED / "host/src/main/res/values/strings.xml"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(b"user resource")
    assert cli(project, "build").returncode == 2
    assert raw.read_bytes() == b"user resource"
    assert not (project / OWNED / "launched").exists()


def test_release_missing_password_env_is_actionable_and_does_not_launch_gradle(
    tmp_path: Path,
) -> None:
    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    project = tmp_path / "demo"
    (project / "key.jks").write_bytes(b"keystore fixture")
    config = project / "pycompose.toml"
    config.write_text(
        config.read_text()
        .replace('keystore = ""', 'keystore = "key.jks"')
        .replace('key_alias = ""', 'key_alias = "release"')
    )
    wrapper(project, 'from pathlib import Path\nPath("launched").touch()\n')
    result = cli(
        project,
        "build",
        "--release",
        env={"PYCOMPOSE_STORE_PASSWORD": "", "PYCOMPOSE_KEY_PASSWORD": ""},
    )
    assert result.returncode == 2
    assert "PYCOMPOSE_STORE_PASSWORD" in result.stderr
    assert not (project / OWNED / "launched").exists()


def test_non_executable_gradle_wrapper_has_a_corrective_message(tmp_path: Path) -> None:
    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    project = tmp_path / "demo"
    wrapper(project, 'raise RuntimeError("must not launch")\n')
    (project / OWNED / "gradlew").chmod(0o644)
    result = cli(project, "build")
    assert result.returncode == 2
    assert "chmod +x gradlew" in result.stderr
    assert "Traceback" not in result.stderr
