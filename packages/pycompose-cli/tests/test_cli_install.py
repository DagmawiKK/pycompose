"""Device installs through a controlled adb, never a real device."""

import json
import sys
from pathlib import Path

from test_cli_build import wrapper
from test_cli_init import cli

_APK = """import zipfile
from pathlib import Path
output = Path("host/build/outputs/apk/debug/host-debug.apk")
output.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(output, "w") as archive:
    archive.writestr("AndroidManifest.xml", "fixture only")
"""

_RELEASE_APK = _APK.replace("debug/host-debug.apk", "release/host-release.apk")

_BUNDLE = """import zipfile
from pathlib import Path
output = Path("host/build/outputs/bundle/release/host-release.aab")
output.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(output, "w") as archive:
    archive.writestr("base/manifest/AndroidManifest.xml", "fixture only")
    archive.writestr("BundleConfig.pb", "fixture only")
"""

_ADB = """import hashlib
import json
import sys
from pathlib import Path

args = sys.argv[1:]
with Path("adb.jsonl").open("a") as log:
    log.write(json.dumps(args) + "\\n")
if args[:1] == ["devices"]:
    print("List of devices attached")
    print("RZ8WB03GR3X\\tdevice")
elif "resolve-activity" in args:
    print("com.example.app_demo/com.pycompose.host.MainActivity")
elif "am" in args:
    print("Starting: Intent")
    print("TotalTime: 321")
elif "md5sum" in args:
    override = Path("device-md5.txt")
    value = override.read_text().strip() if override.is_file() else ""
    if value == "unreported":
        print("md5sum: not found", file=sys.stderr)
        raise SystemExit(1)
    if not value:
        outputs = Path("host/build/outputs/apk")
        artifact = outputs / "debug/host-debug.apk"
        if not artifact.is_file():
            artifact = outputs / "release/host-release.apk"
        value = hashlib.md5(artifact.read_bytes(), usedforsecurity=False).hexdigest()
    print(value + "  /data/app/base.apk")
elif "path" in args:
    print("package:/data/app/base.apk")
elif "install" in args:
    print("Success")
"""


def tools_dir(directory: Path) -> Path:
    tools = directory / "tools"
    tools.mkdir(exist_ok=True)
    adb = tools / "adb"
    adb.write_text(f"#!{sys.executable}\n" + _ADB)
    adb.chmod(0o755)
    return tools


def tools_env(tools: Path | None) -> dict[str, str]:
    return {
        "ANDROID_HOME": "",
        "ANDROID_SDK_ROOT": "",
        "PATH": "" if tools is None else str(tools),
    }


def recorded(project: Path) -> list[list[str]]:
    log = project / "adb.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()]


def signing(tmp_path: Path, project: Path) -> None:
    key = tmp_path / "external key.jks"
    key.write_bytes(b"keystore fixture")
    config = project / "pycompose.toml"
    config.write_text(
        config.read_text()
        .replace('keystore = ""', f"keystore = {json.dumps(str(key))}")
        .replace('key_alias = ""', 'key_alias = "release"')
    )


def test_install_builds_installs_and_verifies_the_device_copy(tmp_path: Path) -> None:
    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    project = tmp_path / "demo"
    wrapper(project, _APK)
    result = cli(project, "install", env=tools_env(tools_dir(tmp_path)))
    assert result.returncode == 0, result.stderr
    assert "Installed com.example.app_demo on RZ8WB03GR3X" in result.stdout
    assert "Digest matches on the device" in result.stdout
    installs = [command for command in recorded(project) if "install" in command]
    assert installs and installs[0][-1].endswith("host-debug.apk")


def test_install_launch_reports_the_device_total_time(tmp_path: Path) -> None:
    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    project = tmp_path / "demo"
    wrapper(project, _APK)
    result = cli(project, "install", "--launch", env=tools_env(tools_dir(tmp_path)))
    assert result.returncode == 0, result.stderr
    assert "Launched in 321 ms" in result.stdout
    assert any("am" in command for command in recorded(project))


def test_debug_launches_unless_told_not_to(tmp_path: Path) -> None:
    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    project = tmp_path / "demo"
    wrapper(project, _APK)
    tools = tools_dir(tmp_path)
    launched = cli(project, "debug", env=tools_env(tools))
    assert launched.returncode == 0, launched.stderr
    assert "Launched in 321 ms" in launched.stdout
    (project / "adb.jsonl").unlink()
    quiet = cli(project, "debug", "--no-launch", env=tools_env(tools))
    assert quiet.returncode == 0, quiet.stderr
    assert "Launched" not in quiet.stdout
    assert not any("am" in command for command in recorded(project))


def test_install_fails_when_the_device_digest_differs(tmp_path: Path) -> None:
    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    project = tmp_path / "demo"
    wrapper(project, _APK)
    (project / "device-md5.txt").write_text("0" * 32)
    result = cli(project, "install", env=tools_env(tools_dir(tmp_path)))
    assert result.returncode == 2
    assert "differs from the built artifact" in result.stderr
    assert "Digest matches" not in result.stdout
    assert "Traceback" not in result.stderr


def test_install_without_a_device_digest_warns_and_still_installs(
    tmp_path: Path,
) -> None:
    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    project = tmp_path / "demo"
    wrapper(project, _APK)
    (project / "device-md5.txt").write_text("unreported")
    result = cli(project, "install", env=tools_env(tools_dir(tmp_path)))
    assert result.returncode == 0, result.stderr
    assert "unverified" in result.stderr


def test_install_without_adb_is_actionable(tmp_path: Path) -> None:
    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    project = tmp_path / "demo"
    wrapper(project, _APK)
    result = cli(project, "install", env=tools_env(None))
    assert result.returncode == 2
    assert "adb missing" in result.stderr
    assert "Traceback" not in result.stderr


def test_release_install_builds_signed_and_installs(tmp_path: Path) -> None:
    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    project = tmp_path / "demo"
    signing(tmp_path, project)
    wrapper(project, _RELEASE_APK)
    env = {
        **tools_env(tools_dir(tmp_path)),
        "PYCOMPOSE_STORE_PASSWORD": "store-secret",
        "PYCOMPOSE_KEY_PASSWORD": "key-secret",
    }
    result = cli(project, "release", "apk", "--install", env=env)
    assert result.returncode == 0, result.stderr
    assert "Installed com.example.app_demo" in result.stdout
    installs = [command for command in recorded(project) if "install" in command]
    assert installs and installs[0][-1].endswith("host-release.apk")


def test_release_install_refuses_a_bundle(tmp_path: Path) -> None:
    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    project = tmp_path / "demo"
    signing(tmp_path, project)
    wrapper(project, _BUNDLE)
    env = {
        **tools_env(tools_dir(tmp_path)),
        "PYCOMPOSE_STORE_PASSWORD": "store-secret",
        "PYCOMPOSE_KEY_PASSWORD": "key-secret",
    }
    result = cli(project, "release", "aab", "--install", env=env)
    assert result.returncode == 2
    assert "needs a single APK" in result.stderr
