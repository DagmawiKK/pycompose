"""Run orchestration through controlled executables, not a physical device."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_cli_build import wrapper
from test_cli_init import cli


def test_run_builds_installs_launches_and_cleans_up_its_reverse_tunnel(
    tmp_path: Path,
) -> None:
    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    project = tmp_path / "demo"
    wrapper(
        project,
        """import zipfile
from pathlib import Path
p = Path("host/build/outputs/apk/debug/host-debug.apk")
p.parent.mkdir(parents=True)
with zipfile.ZipFile(p, "w") as archive:
    archive.writestr("AndroidManifest.xml", "fixture only")
""",
    )
    tools = tmp_path / "tools"
    tools.mkdir()
    adb = tools / "adb"
    adb.write_text(
        f"#!{sys.executable}\n"
        + """import json, sys
from pathlib import Path
with Path("adb.jsonl").open("a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:] == ["devices"]:
    print("List of devices attached\\nfixture-device\\tdevice")
"""
    )
    adb.chmod(0o755)
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).parents[1]),
        "PATH": str(tools),
        "ANDROID_HOME": "",
        "ANDROID_SDK_ROOT": "",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "pycompose_cli", "run"],
        cwd=project,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        launched = False
        while time.monotonic() < deadline and process.poll() is None:
            log = project / "adb.jsonl"
            commands = (
                [json.loads(line) for line in log.read_text().splitlines()]
                if log.exists()
                else []
            )
            if any("start" in command for command in commands):
                launched = True
                break
            time.sleep(0.02)
        assert launched
        process.send_signal(signal.SIGINT)
        output, errors = process.communicate(timeout=5)
        assert process.returncode == 0, output + errors
        commands = [
            json.loads(line)
            for line in (project / "adb.jsonl").read_text().splitlines()
        ]
        assert any(
            command[:4] == ["-s", "fixture-device", "install", "-r"]
            for command in commands
        )
        assert any(
            "com.example.app_demo/com.pycompose.host.MainActivity" in command
            for command in commands
        )
        assert any(command[2:4] == ["reverse", "--remove"] for command in commands)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


@pytest.mark.parametrize(
    "devices",
    ["", "offline\toffline", "locked\tunauthorized", "first\tdevice\nsecond\tdevice"],
)
def test_run_rejects_unavailable_or_ambiguous_devices_before_building(
    tmp_path: Path, devices: str
) -> None:
    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    tools = tmp_path / "tools"
    tools.mkdir()
    adb = tools / "adb"
    adb.write_text(
        f'#!{sys.executable}\nprint({("List of devices attached\n" + devices)!r})\n'
    )
    adb.chmod(0o755)
    result = cli(
        tmp_path / "demo",
        "run",
        env={
            "PATH": str(tools),
            "ANDROID_HOME": "",
            "ANDROID_SDK_ROOT": "",
            "ANDROID_SERIAL": "",
        },
    )
    assert result.returncode == 2
    assert "connect one authorized device" in result.stderr
    assert "Traceback" not in result.stderr


def test_run_missing_adb_is_actionable(tmp_path: Path) -> None:
    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    result = cli(
        tmp_path / "demo",
        "run",
        env={"PATH": "", "ANDROID_HOME": "", "ANDROID_SDK_ROOT": ""},
    )
    assert result.returncode == 2
    assert "adb missing" in result.stderr


def test_run_on_the_dev_client_installs_it_and_serves_the_app(tmp_path: Path) -> None:
    import zipfile

    from pycompose_cli.dev_client import FINGERPRINT, framework_fingerprint

    from pycompose.version import __version__

    assert cli(tmp_path, "init", "demo", "--native").returncode == 0
    project = tmp_path / "demo"
    # A Gradle run would fail: the dev client is used, the app is not built.
    wrapper(project, "raise SystemExit(9)\n")
    home = tmp_path / "home"
    client = home / "dev-client" / __version__ / "dev-client.apk"
    client.parent.mkdir(parents=True)
    with zipfile.ZipFile(client, "w") as archive:
        archive.writestr("AndroidManifest.xml", "fixture only")
    (client.parent / FINGERPRINT).write_text(framework_fingerprint())
    tools = tmp_path / "tools"
    tools.mkdir()
    adb = tools / "adb"
    adb.write_text(
        f"#!{sys.executable}\n"
        + """import json, sys
from pathlib import Path
with Path("adb.jsonl").open("a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:] == ["devices"]:
    print("List of devices attached\\nfixture-device\\tdevice")
"""
    )
    adb.chmod(0o755)
    # The SDK's adb wins over PATH: an exported ANDROID_HOME would reach a real
    # device instead of the fixture.
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).parents[1]),
        "PATH": str(tools),
        "PYCOMPOSE_HOME": str(home),
        "ANDROID_HOME": "",
        "ANDROID_SDK_ROOT": "",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "pycompose_cli", "run", "--dev-client"],
        cwd=project,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    log = project / "adb.jsonl"
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and process.poll() is None:
            if log.exists() and "start" in log.read_text():
                break
            time.sleep(0.02)
        process.send_signal(signal.SIGINT)
        output, errors = process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
    assert process.returncode == 0, output + errors
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    install = next(c for c in commands if "install" in c)
    assert install[-1] == str(client)
    start = next(c for c in commands if "start" in c)
    assert "com.pycompose.devclient/com.pycompose.host.MainActivity" in start
    assert start[start.index("pycompose.dev.source") + 1] == "app"


def test_a_dev_client_built_from_another_framework_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pycompose_cli import dev_client
    from pycompose_cli.project import ProjectError

    from pycompose.version import __version__

    monkeypatch.setattr(dev_client, "HOME", tmp_path / "home" / "toolchain")
    client = tmp_path / "home" / "dev-client" / __version__ / "dev-client.apk"
    client.parent.mkdir(parents=True)
    client.write_bytes(b"apk")
    (client.parent / dev_client.FINGERPRINT).write_text("built-from-before\n")
    # Running it would serve the app to a framework without today's API.
    with pytest.raises(ProjectError, match="dev-client --rebuild"):
        dev_client.dev_client()
    (client.parent / dev_client.FINGERPRINT).write_text(
        dev_client.framework_fingerprint()
    )
    assert dev_client.dev_client() == client


def test_bench_types_into_the_app_and_summarizes_each_stage(tmp_path: Path) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    adb = tools / "adb"
    lines = [
        {"queue": q, "python": p, "frame": 8.0, "view": p / 2, "commands": 1}
        for q, p in ((1.0, 40.0), (2.0, 60.0), (30.0, 200.0))
    ]
    adb.write_text(
        f"#!{sys.executable}\n"
        + f"""import json, sys
from pathlib import Path
with Path("adb.jsonl").open("a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:] == ["devices"]:
    print("List of devices attached\\nfixture-device\\tdevice")
if "-d" in sys.argv:
    print("--------- beginning of main")
    for line in {[json.dumps(line) for line in lines]!r}:
        print(line)
"""
    )
    adb.chmod(0o755)
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).parents[1]),
        "PATH": str(tools),
        "ANDROID_HOME": "",
        "ANDROID_SDK_ROOT": "",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pycompose_cli",
            "bench",
            "--keys",
            "3",
            "--interval",
            "0",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "3 passes for 3 keystrokes" in result.stdout
    python = next(
        line for line in result.stdout.splitlines() if line.startswith("python")
    )
    assert python.split()[1:] == ["60.0", "200.0", "200.0"]
    commands = [
        json.loads(line) for line in (tmp_path / "adb.jsonl").read_text().splitlines()
    ]
    assert sum("keyevent" in command for command in commands) == 3
