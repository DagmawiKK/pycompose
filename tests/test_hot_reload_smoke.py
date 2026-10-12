"""Desktop reload smoke; native delivery and overlay acceptance are separate."""

import json
import time
import urllib.request
from pathlib import Path

import pytest
from test_cli_init import cli


@pytest.mark.hot_reload_smoke
def test_python_edit_produces_a_new_full_snapshot_without_gradle(
    tmp_path: Path,
) -> None:
    from pycompose.cli.dev_server import DevServer
    from pycompose.cli.project import load_project

    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    with DevServer(load_project(project)) as server:
        request = urllib.request.Request(
            server.url + "/session", headers={"Authorization": f"Bearer {server.token}"}
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            initial = json.load(response)
        assert (
            json.loads(initial["snapshot"])["root"]["props"]["text"]
            == "Hello PyCompose"
        )
        main = project / "app" / "main.py"
        main.write_text(main.read_text().replace("Hello PyCompose", "Reloaded screen"))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with urllib.request.urlopen(request, timeout=5) as response:
                current = json.load(response)
            if current["revision"] > initial["revision"]:
                break
            time.sleep(0.02)
        assert current["revision"] > initial["revision"]
        assert (
            json.loads(current["snapshot"])["root"]["props"]["text"]
            == "Reloaded screen"
        )
        assert current["diagnostics"]["nodeCount"] == 1
        assert current["diagnostics"]["lastError"] is None
        assert not (project / "host" / "build").exists()
