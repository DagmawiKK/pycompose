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
from test_cli_init import cli

from pycompose.cli.dev_server import DevServer
from pycompose.cli.project import load_project
from pycompose.ir.generated_validators import SCHEMA_VERSION


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
        main.write_text(source.replace("Hello PyCompose", "Recovered screen"))
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
        "from screen_text import TITLE\nfrom pycompose.components import Text\n"
        "from pycompose.state import App, State\ndef view(restore):\n"
        '    return State(root=Text(id="greeting", text=TITLE))\n'
        "app = App(view=view)\n"
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


PREVIEW_APP = '''\
from typing import TypedDict

from pycompose import Registry, composable
from pycompose.components import Button
from pycompose.state import App, AppState


class Shell(AppState):
    """The preview shell."""

    taps: int = 0


actions = Registry()


@actions
def tap(session: Shell) -> Shell:
    """Count one tap.

    Args:
        session: The shell before the tap.
        payload: Empty; this command takes no event fields.

    Returns:
        The shell with one more tap.
    """
    return Shell(taps=session.taps + 1)


@composable
def screen(session: Shell, actions: Registry | None = None) -> Button:
    """Bind the button this preview must resolve the registry for.

    Args:
        session: The shell after the entry ran.
        actions: The module's registry, filled from the app context.

    Returns:
        A bound button.
    """
    return Button(
        id="tap_button",
        text=f"tapped:{session.taps}",
        on_click=actions.tap.binding(),
    )


def view(session: Shell) -> Button:
    """Render the screen for this shell.

    Args:
        session: The shell after the entry ran.

    Returns:
        The bound button screen.
    """
    return screen(id="screen", session=session)


app = App(state=Shell, view=view)
'''


def test_the_preview_resolves_the_modules_actions_for_a_context_reaching_screen(
    tmp_path: Path,
) -> None:
    from pycompose.cli.reload import AppReloader

    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    (project / "app" / "main.py").write_text(PREVIEW_APP, encoding="utf-8")

    reloader = AppReloader(load_project(project), SCHEMA_VERSION)
    try:
        snapshot = json.loads(reloader.snapshot())
    finally:
        # The reloader owns the import path and the user modules; without
        # close() the demo's `main` would shadow the next app's entrypoint.
        reloader.close()

    assert snapshot["root"]["props"]["text"] == "tapped:0"
