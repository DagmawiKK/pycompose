"""Hot reload of an app built from view models, with work in flight."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from pycompose_testing.simulator import Simulator

from pycompose.bridge.session import RuntimeSession

APP = """
import asyncio
from pycompose.app import App, Destination, Intent, ViewModel
from pycompose.foundation import Column
from pycompose.material3 import Button, Text
from pycompose.state import AppState


class Counter(AppState):
    count: int = 0
    done: bool = False


class SetCount(Intent):
    count: int


class Work(Intent):
    pass


class Container:
    def __init__(self):
        self.built = []
        self.cleared = []
        self.closed = False

    def close(self):
        self.closed = True


class CounterViewModel(ViewModel[Counter]):
    def __init__(self, container):
        super().__init__(Counter())
        self.container = container
        container.built.append(LABEL)

    def on_intent(self, intent):
        if isinstance(intent, SetCount):
            self.state = self.state.evolve(count=intent.count)
        elif isinstance(intent, Work):
            self.launch(self.work())

    async def work(self):
        await asyncio.sleep(10)
        self.state = self.state.evolve(done=True)

    def on_cleared(self):
        self.container.cleared.append(LABEL)


def screen(state):
    return Column(children=[
        Text(id="label", text=f"{LABEL}:{state.count}:{state.done}"),
        Button(id="three", text="3", on_click=SetCount(count=3)),
        Button(id="work", text="work", on_click=Work()),
    ])


app = App(
    start=Destination(lambda container, route: CounterViewModel(container), screen),
    container=Container,
)
"""


@pytest.fixture
def source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    package = tmp_path / "app" / "reload_app"
    package.mkdir(parents=True)
    module = package / "main.py"
    module.write_text('LABEL = "v1"\n' + APP)
    monkeypatch.syspath_prepend(str(tmp_path / "app"))
    yield module
    for name in [n for n in sys.modules if n.startswith("reload_app")]:
        del sys.modules[name]
    shutil.rmtree(package / "__pycache__", ignore_errors=True)


def _label(session: RuntimeSession) -> str:
    root = json.loads(session.snapshot())["root"]
    paths = session.node_paths()
    return next(c for c in root["children"] if paths[c["id"]].endswith("label"))[
        "props"
    ]["text"]


def _tap(session: RuntimeSession, node: str) -> None:
    root = json.loads(session.snapshot())["root"]
    paths = session.node_paths()
    target = next(c for c in root["children"] if paths[c["id"]].endswith(node))
    session.accept_action(json.dumps({**target["props"]["onClick"], "payload": {}}))


def _refresh(session: RuntimeSession) -> None:
    session.accept_action(json.dumps({"intent": "pycompose.refresh", "payload": {}}))


def test_a_reload_rebuilds_from_saved_state_and_cancels_work_in_flight(
    source: Path,
) -> None:
    sim = Simulator()

    async def run() -> None:
        session = RuntimeSession("reload_app.main:app", "", debug=True)
        _tap(session, "three")
        _tap(session, "work")
        container = session._container

        # The edit, a different length so stale bytecode cannot be used.
        source.write_text('LABEL = "v2 edited"\n' + APP)
        assert session.reload("", "")
        # Clearing cancels the old work and waits for it to end.
        await asyncio.sleep(1)

        # The new code drew the old view model's saved state.
        assert _label(session) == "v2 edited:3:False"
        # The container survived; the old view model was cleared, its work
        # with it, and the new one was built once.
        assert session._container is container
        assert not container.closed
        assert container.built == ["v1", "v2 edited"]
        assert container.cleared == ["v1"]

        # The old work would have finished by now; it was cancelled instead.
        await asyncio.sleep(20)
        _refresh(session)
        assert _label(session) == "v2 edited:3:False"
        assert session.error() == ""
        # The container ends with the session, not with a reload.
        session.close()
        assert container.closed

    sim.run(run())
    assert sim.failures == []
    sim.close()


def test_a_failed_reload_changes_nothing(source: Path) -> None:
    sim = Simulator()

    async def run() -> None:
        session = RuntimeSession("reload_app.main:app", "", debug=True)
        _tap(session, "three")
        _tap(session, "work")
        container = session._container

        source.write_text('LABEL = "broken"\n' + APP + "\nthis is not python\n")
        assert not session.reload("", "")
        assert session.error() != ""
        assert _label(session) == "v1:3:False"
        assert container.cleared == []

        # The work in flight was never touched, and still finishes.
        await asyncio.sleep(20)
        _refresh(session)
        assert _label(session) == "v1:3:True"

        # The next good edit reloads from the state that work produced.
        source.write_text('LABEL = "v3 fixed"\n' + APP)
        assert session.reload("", "")
        assert _label(session) == "v3 fixed:3:True"
        session.close()

    sim.run(run())
    assert sim.failures == []
    sim.close()


def test_the_desktop_preview_reloads_an_app_built_from_view_models(
    source: Path, tmp_path: Path
) -> None:
    from pycompose_cli.devloop.reload import AppReloader
    from pycompose_cli.project import load_project

    (tmp_path / "pycompose.toml").write_text(
        '[app]\nname = "Reload"\napplication_id = "com.example.reload"\n'
        '[python]\nentrypoint = "reload_app.main:app"\nsource_dir = "app"\n'
    )
    reloader = AppReloader(load_project(tmp_path))
    try:
        first = json.loads(reloader.snapshot())
        source.write_text('LABEL = "v2 edited"\n' + APP)
        second = json.loads(reloader.snapshot())
    finally:
        reloader.close()
    assert first["root"]["children"][0]["props"]["text"] == "v1:0:False"
    assert second["root"]["children"][0]["props"]["text"] == "v2 edited:0:False"
