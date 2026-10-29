"""Authenticated dev bundles and last-good previews at the HTTP boundary."""

import base64
import json
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pycompose_cli.dev_server import DevServer
from pycompose_cli.project import load_project
from test_cli_init import cli


def session(server: DevServer) -> dict[str, Any]:
    request = urllib.request.Request(
        server.url + "/session", headers={"Authorization": f"Bearer {server.token}"}
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.headers["Cache-Control"] == "no-store"
        return json.load(response)


def wait_for(
    server: DevServer, predicate: Callable[[dict[str, Any]], bool]
) -> dict[str, Any]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        data = session(server)
        if predicate(data):
            return data
        time.sleep(0.02)
    raise AssertionError(f"reload did not arrive: {data}")


def test_failed_reload_preserves_the_last_good_snapshot_and_files_then_recovers(
    tmp_path: Path,
) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    with DevServer(load_project(project)) as server:
        initial = session(server)
        main = project / "app" / "main.py"
        source = main.read_text()
        main.write_text("syntax error here\n")
        broken = wait_for(
            server, lambda data: data["diagnostics"]["lastError"] is not None
        )
        assert broken["snapshot"] == initial["snapshot"]
        assert broken["files"] == initial["files"]
        assert broken["revision"] == initial["revision"]
        main.write_text(
            source.replace("Type your name and tap Greet.", "Recovered screen")
        )
        recovered = wait_for(
            server, lambda data: data["revision"] > initial["revision"]
        )
        assert recovered["diagnostics"]["lastError"] is None
        assert "Recovered screen" in recovered["snapshot"]


def test_resource_bundles_publish_deletions_and_keep_drawable_rebuild_flag(
    tmp_path: Path,
) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    with DevServer(load_project(project)) as server:
        initial = session(server)
        asset = project / "resources" / "assets" / "data.bin"
        asset.write_bytes(b"runtime bytes")
        current = wait_for(server, lambda data: data["revision"] > initial["revision"])
        assert (
            base64.b64decode(current["files"]["resources/assets/data.bin"])
            == b"runtime bytes"
        )
        assert not current["requiresRebuild"]
        asset.unlink()
        removed = wait_for(server, lambda data: data["revision"] > current["revision"])
        assert "resources/assets/data.bin" not in removed["files"]
        (project / "resources" / "drawables" / "logo.png").write_bytes(b"image")
        drawable = wait_for(server, lambda data: data["revision"] > removed["revision"])
        assert drawable["requiresRebuild"]
        (project / "resources" / "strings.json").write_text('{"title":"new"}')
        after = wait_for(server, lambda data: data["revision"] > drawable["revision"])
        assert after["requiresRebuild"]


def test_authentication_and_unknown_paths_do_not_expose_project_files(
    tmp_path: Path,
) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    with DevServer(load_project(tmp_path / "demo")) as server:
        for path, headers, status in [
            ("/session", {}, 401),
            ("/session", {"Authorization": "Bearer wrong"}, 401),
            ("/../../pycompose.toml", {"Authorization": f"Bearer {server.token}"}, 404),
        ]:
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(
                    urllib.request.Request(server.url + path, headers=headers),
                    timeout=5,
                )
            assert exc.value.code == status
        assert session(server)["snapshot"] is not None


def test_failed_socket_bind_releases_the_session_lock(tmp_path: Path) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = load_project(tmp_path / "demo")
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        with pytest.raises(OSError), DevServer(project, port=occupied.getsockname()[1]):
            pass
    with DevServer(project) as server:
        assert session(server)["snapshot"] is not None


def test_imported_user_module_edits_reload_before_entrypoint_and_cache_is_fresh(
    tmp_path: Path,
) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    helper = project / "app" / "screen_text.py"
    helper.write_text('TITLE = "First"\n')
    (project / "app" / "main.py").write_text(
        "from screen_text import TITLE\nfrom pycompose.ui import Text\n"
        "from pycompose.app import App, Destination, ViewModel\n"
        "from pycompose.state import AppState\n"
        "class Greeting(AppState):\n    pass\n"
        "class GreetingViewModel(ViewModel[Greeting]):\n"
        "    def __init__(self):\n        super().__init__(Greeting())\n"
        "def screen(state):\n"
        '    return Text(id="greeting", text=TITLE)\n'
        "app = App(start=Destination(lambda _c, _r: GreetingViewModel(), screen))\n"
    )
    with DevServer(load_project(project)) as server:
        initial = session(server)
        helper.write_text('TITLE = "Other"\n')
        updated = wait_for(server, lambda data: data["revision"] > initial["revision"])
        assert json.loads(updated["snapshot"])["root"]["props"]["text"] == "Other"
        helper.write_text('TITLE = "Third"\n')
        again = wait_for(server, lambda data: data["revision"] > updated["revision"])
        assert json.loads(again["snapshot"])["root"]["props"]["text"] == "Third"


def test_symlinked_resources_are_rejected_without_exposing_external_bytes(
    tmp_path: Path,
) -> None:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    secret = tmp_path / "secret"
    secret.write_bytes(b"external private bytes")
    with DevServer(load_project(project)) as server:
        initial = session(server)
        (project / "resources" / "assets" / "secret").symlink_to(secret)
        failed = wait_for(
            server, lambda data: data["diagnostics"]["lastError"] is not None
        )
        assert failed["files"] == initial["files"]
        assert "resources/assets/secret" not in failed["files"]


COUNTER = """
from m3 import Button, Column, Text
from pycompose.app import App, Destination, Intent, ViewModel
from pycompose.state import AppState


class Counter(AppState):
    count: int = 0


class Increment(Intent):
    pass


class CounterViewModel(ViewModel[Counter]):
    def __init__(self):
        super().__init__(Counter())

    def on_intent(self, intent):
        self.state = self.state.evolve(count=self.state.count + 1)


def screen(state):
    return Column(
        children=[Text(text="Counted"), Button(text="Tap", on_click=Increment())]
    )


app = App(start=Destination(lambda _c, _r: CounterViewModel(), screen))
"""


def test_a_component_used_for_the_first_time_reloads_without_a_build(
    tmp_path: Path,
) -> None:
    # Found on an emulator: the dev client runs the whole catalog, but the app's
    # generated package only had the scaffold's Text, so Button failed to import.
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    with DevServer(load_project(project)) as server:
        initial = session(server)
        (project / "app" / "main.py").write_text(COUNTER)
        reloaded = wait_for(server, lambda data: data["revision"] > initial["revision"])
        assert reloaded["diagnostics"]["lastError"] is None
        assert '"Button"' in reloaded["snapshot"]


def test_another_apps_module_of_the_same_name_never_stands_in(tmp_path: Path) -> None:
    import sys
    import types

    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    (project / "app" / "main.py").write_text(COUNTER)
    stale = types.ModuleType("m3")  # an earlier app's package, with no Button
    sys.modules["m3"] = stale
    try:
        with DevServer(load_project(project)) as server:
            assert session(server)["diagnostics"]["lastError"] is None
        assert sys.modules["m3"] is stale
    finally:
        sys.modules.pop("m3", None)
