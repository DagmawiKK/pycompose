"""On-device module lifecycle through the pure-data Python runtime seam."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from pycompose.bridge import runtime
from pycompose.errors import BridgeError, StateError

SOURCE = """
import threading
import device_helper
from pycompose.app import App, Destination, Intent, ViewModel
from pycompose.foundation import Column
from pycompose.material3 import Button, Text
from pycompose.state import AppState

BUILT = []


class Counter(AppState):
    n: int = 0
    thread: str = ""


class Bump(Intent):
    pass


class Container:
    def __init__(self):
        BUILT.append(self)


class CounterViewModel(ViewModel[Counter]):
    def __init__(self, container):
        super().__init__(Counter(thread=threading.current_thread().name))
        self.container = container

    def on_intent(self, intent):
        self.state = self.state.evolve(n=self.state.n + 1)


def screen(state):
    return Column(children=[
        Text(id="text", text=f"{LABEL}:{device_helper.label}:{state.n}"),
        Button(id="bump", text="+", on_click=Bump()),
    ])


app = App(
    start=Destination(lambda container, _route: CounterViewModel(container), screen),
    container=Container,
)
"""


@pytest.fixture
def device(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    (tmp_path / "device_helper.py").write_text('label = "helper"\n')
    module = tmp_path / "device_app.py"
    module.write_text('LABEL = "first"\n' + SOURCE)
    monkeypatch.syspath_prepend(str(tmp_path))
    yield module
    runtime.close()
    for name in ("device_app", "device_helper"):
        sys.modules.pop(name, None)


def snapshot() -> dict:
    return json.loads(runtime.fetch_latest_snapshot())


def text() -> str:
    return snapshot()["root"]["children"][0]["props"]["text"]


def bump() -> None:
    target = snapshot()["root"]["children"][1]["props"]["onClick"]
    runtime.accept_action(json.dumps({**target, "payload": {}}))


def test_build_intent_reload_and_a_bad_reload_that_keeps_the_snapshot(
    device: Path,
) -> None:
    runtime.start("device_app:app", "", True)
    assert text() == "first:helper:0"
    bump()
    assert text() == "first:helper:1"

    device.write_text('LABEL = "reloaded"\n' + SOURCE)
    assert runtime.reload("", "") is True
    assert text() == "reloaded:helper:1"

    previous = runtime.fetch_latest_snapshot()
    device.write_text('raise RuntimeError("broken app")\n')
    assert runtime.reload("", "") is False
    assert runtime.fetch_latest_snapshot() == previous
    assert "broken app" in runtime.fetch_latest_error()


def test_the_container_is_built_once_and_kept_across_reloads(device: Path) -> None:
    runtime.start("device_app:app", "", True)
    built = sys.modules["device_app"].BUILT
    assert len(built) == 1

    device.write_text('raise RuntimeError("broken app")\n')
    runtime.reload("", "")
    device.write_text('LABEL = "recovered"\n' + SOURCE)
    assert runtime.reload("", "") is True

    # The fresh module's factory never ran: the session kept its container.
    assert sys.modules["device_app"].BUILT == []
    assert len(built) == 1


def test_a_failed_reload_restores_the_app_module_graph(device: Path) -> None:
    runtime.start("device_app:app", "", True)
    (device.parent / "device_helper.py").write_text('label = "failed candidate"\n')
    device.write_text('import device_helper\nraise RuntimeError("broken")\n')
    assert runtime.reload("", "") is False

    bump()
    assert text() == "first:helper:1"


def test_a_reloaded_session_answers_an_old_serial_with_the_whole_snapshot(
    device: Path,
) -> None:
    runtime.start("device_app:app", "", True)
    first = json.loads(runtime.fetch_latest("main", -1))
    assert first["kind"] == "full"
    bump()
    patch = json.loads(runtime.fetch_latest("main", first["serial"]))
    assert (patch["kind"], patch["baseSerial"]) == ("patch", first["serial"])

    device.write_text('LABEL = "reloaded"\n' + SOURCE)
    assert runtime.reload("", "") is True
    assert json.loads(runtime.fetch_latest("main", patch["serial"]))["kind"] == "full"


@pytest.mark.usefixtures("device")
def test_view_models_are_built_on_the_loop_thread() -> None:
    runtime.start("device_app:app", "", False)
    assert snapshot()["metadata"]["data"]["stack"][0]["state"]["thread"] == (
        "pycompose-loop"
    )


def test_a_container_that_is_not_callable_is_refused() -> None:
    from pycompose.app import App, Destination

    with pytest.raises(StateError, match="zero-argument callable"):
        App(start=Destination(lambda _c, _r: None, lambda _s: None), container=object())  # type: ignore[arg-type,return-value]


def test_an_entrypoint_that_names_no_app_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pycompose.bridge.session import RuntimeSession

    (tmp_path / "no_export_app.py").write_text('label = "not an app"\n')
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        with pytest.raises(BridgeError, match="App export"):
            RuntimeSession("no_export_app:label", "home", debug=True)
    finally:
        sys.modules.pop("no_export_app", None)


def test_the_removed_app_model_names_its_replacement() -> None:
    with pytest.raises(ImportError, match=r"pycompose\.app\.App"):
        from pycompose.state import App  # noqa: F401
    with pytest.raises(ImportError, match="Intent"):
        from pycompose import action  # noqa: F401
