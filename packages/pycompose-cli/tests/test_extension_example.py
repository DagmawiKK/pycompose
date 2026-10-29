"""The example app uses HTTPX and SQLite directly, their calls off the loop."""

import json
import queue
import shutil
import sys
from pathlib import Path

import pytest
from test_cli_build import wrapper
from test_cli_init import cli
from test_cli_permissions import declare

from pycompose.bridge import runtime
from pycompose.storage import paths


def prepare_example(tmp_path: Path) -> Path:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    declare(project, requirements=["httpx>=0.27,<0.29"], internet=True)
    source = project / "app"
    sample = Path(__file__).resolve().parents[3] / "examples/extensions/app/main.py"
    shutil.copyfile(sample, source / "extension_example.py")
    (source / "main.py").write_text("from extension_example import app\n")
    (source / "settings.py").write_text("""import httpx
BASE_URL = "https://fixture.test"
requested = []
offline = False
def reply(request):
    requested.append(request.url.path)
    if offline:
        raise AssertionError("cache read tried the network")
    field = "name" if request.url.path in {"/comments", "/users"} else "title"
    return httpx.Response(200, json=[{"id": 1, field: request.url.path + " café"}])
HTTP_OPTIONS = {"transport": httpx.MockTransport(reply)}
""")
    wrapper(
        project,
        """import zipfile
from pathlib import Path
path = Path("host/build/outputs/apk/debug/host-debug.apk")
path.parent.mkdir(parents=True)
with zipfile.ZipFile(path, "w") as output:
    output.writestr("AndroidManifest.xml", "fixture only")
""",
    )
    result = cli(project, "build")
    assert result.returncode == 0, result.stderr
    return source


def test_http_page_is_cached_and_restored_offline_through_the_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = prepare_example(tmp_path)
    monkeypatch.syspath_prepend(str(source))
    files, cache = tmp_path / "files", tmp_path / "cache"
    files.mkdir()
    cache.mkdir()
    pending: queue.Queue[str] = queue.Queue()

    def listen() -> None:
        runtime.install_async_sink(
            lambda event, data: pending.put(
                json.dumps({"intent": event, "payload": json.loads(data)})
            )
        )

    def intent(name: str, **fields: str) -> None:
        runtime.accept_action(
            json.dumps(
                {
                    "fields": fields,
                    "intent": f"extension_example.{name}",
                    "payload": {},
                }
            )
        )

    def finished() -> None:
        # The work signals once it has changed the state; the signal comes back
        # as an action, as the host delivers it, and publishes that state.
        runtime.accept_action(pending.get(timeout=3))

    previous = {
        name: module
        for name, module in sys.modules.items()
        if name in {"settings", "extension_example", "m3"} or name.startswith("m3.")
    }
    for name in previous:
        sys.modules.pop(name)
    try:
        first = runtime.start(
            "extension_example:app",
            "home",
            True,
            files_dir=str(files),
            cache_dir=str(cache),
        )
        assert paths().files == files
        assert paths().cache == cache
        listen()
        endpoints = ("/posts", "/comments", "/albums", "/photos", "/todos", "/users")

        for endpoint in endpoints:
            intent("ChooseEndpoint", endpoint=endpoint)
            intent("Refresh")
            finished()
            assert endpoint + " café" in runtime.fetch_latest_snapshot()
            assert "HTTP 200" in runtime.fetch_latest_snapshot()
            assert runtime.fetch_latest_error() == ""
        assert sys.modules["settings"].requested == list(endpoints)

        # New session, same private files. Cache reads require no HTTP operation.
        second = runtime.start(
            "extension_example:app",
            "home",
            True,
            files_dir=str(files),
            cache_dir=str(cache),
        )
        runtime.close(first)  # Obsolete native teardown cannot close its replacement.
        listen()
        sys.modules["settings"].offline = True
        for endpoint in endpoints:
            intent("ChooseEndpoint", endpoint=endpoint)
            intent("LoadCache")
            finished()
            assert endpoint + " café" in runtime.fetch_latest_snapshot()
            assert "SQLite cache" in runtime.fetch_latest_snapshot()
            assert runtime.fetch_latest_error() == ""
        assert sys.modules["settings"].requested == list(endpoints)
        runtime.close(second)
    finally:
        runtime.close()
        for name in tuple(sys.modules):
            if name in {"settings", "extension_example", "m3"} or name.startswith(
                "m3."
            ):
                sys.modules.pop(name, None)
        sys.modules.update(previous)
