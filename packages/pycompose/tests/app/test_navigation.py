"""The back stack: a view model per screen, back to pop, saved across restarts."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from pycompose.bridge import runtime
from pycompose.runtime import signal

APP = """
import asyncio
from pycompose.app import App, Destination, Intent, Push, Route, ViewModel
from pycompose.ui import Column
from pycompose.ui import Button, Text
from pycompose.state import AppState


class ListRoute(Route):
    pass


class DetailRoute(Route):
    id: int


class ListState(AppState):
    opened: int = 0


class DetailState(AppState):
    id: int = 0
    edits: int = 0
    resumed: int = 0


class Open(Intent):
    id: int


class Edit(Intent):
    pass


CLEARED = []
TRIMMED = []


class ListViewModel(ViewModel[ListState]):
    def __init__(self):
        super().__init__(ListState())

    def on_trim_memory(self, level):
        TRIMMED.append(("list", level))

    def on_intent(self, intent):
        if isinstance(intent, Open):
            self.state = self.state.evolve(opened=intent.id)
            self.navigate(Push(DetailRoute(id=intent.id)))


class DetailViewModel(ViewModel[DetailState]):
    def __init__(self, route):
        if route.id == 13:
            raise RuntimeError("detail 13 cannot be built")
        super().__init__(DetailState(id=route.id))
        self.launch(self.forever())

    async def forever(self):
        try:
            await asyncio.Event().wait()
        finally:
            CLEARED.append(self.state.id)

    def on_intent(self, intent):
        if isinstance(intent, Edit):
            self.state = self.state.evolve(edits=self.state.edits + 1)

    def on_resume(self):
        self.state = self.state.evolve(resumed=self.state.resumed + 1)

    def on_trim_memory(self, level):
        TRIMMED.append(("detail", level))


def list_screen(state):
    return Column(children=[
        Text(id="title", text=f"list:{state.opened}"),
        Button(id="open", text="Open", on_click=Open(id=7)),
    ])


def detail_screen(state):
    return Column(children=[
        Text(id="title", text=f"detail:{state.id}:{state.edits}:{state.resumed}"),
        Button(id="edit", text="Edit", on_click=Edit()),
    ])


app = App(
    start=ListRoute(),
    destinations={
        ListRoute: Destination(lambda c, r: ListViewModel(), list_screen),
        DetailRoute: Destination(lambda c, r: DetailViewModel(r), detail_screen),
    },
    deep_links=frozenset({DetailRoute}),
)
"""


@pytest.fixture
def notes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    (tmp_path / "nav_app.py").write_text(APP)
    monkeypatch.syspath_prepend(str(tmp_path))
    yield "nav_app:app"
    runtime.close()
    signal.install(None)
    sys.modules.pop("nav_app", None)


def _snapshot() -> dict:
    return json.loads(runtime.fetch_latest_snapshot())


def _title() -> str:
    return _snapshot()["root"]["children"][0]["props"]["text"]


def _tap(node_index: int) -> None:
    intent = _snapshot()["root"]["children"][node_index]["props"]["onClick"]
    runtime.accept_action(json.dumps({**intent, "payload": {}}))


def _event(name: str, **payload: object) -> None:
    runtime.accept_action(json.dumps({"intent": name, "payload": payload}))


def _settle() -> None:
    runtime._loop_thread().call(lambda: None)
    runtime._loop_thread().call(lambda: None)


def test_a_push_shows_the_new_screen_and_records_its_route(notes: str) -> None:
    runtime.start(notes, "home", True)
    assert _title() == "list:0"
    _tap(1)
    snapshot = _snapshot()
    assert _title() == "detail:7:0:0"
    (navigate,) = snapshot["metadata"]["effects"]
    assert navigate["kind"] == "navigate"
    assert json.loads(navigate["payload"]["route"])["fields"] == {"id": 7}
    # The host echoes the route it recorded; the screen it names is already open.
    _event("onRouteChanged", route=navigate["payload"]["route"])
    assert _title() == "detail:7:0:0"


def test_back_pops_the_screen_and_cancels_its_work(notes: str) -> None:
    runtime.start(notes, "home", True)
    _tap(1)
    _event("onBackRequested")
    _settle()
    assert _title() == "list:7"
    assert sys.modules["nav_app"].CLEARED == [7]


def test_back_on_the_first_screen_finishes(notes: str) -> None:
    runtime.start(notes, "home", True)
    _event("onBackRequested")
    assert _snapshot()["metadata"]["effects"] == [{"kind": "finish", "payload": {}}]


def test_lifecycle_reaches_the_top_screen(notes: str) -> None:
    runtime.start(notes, "home", True)
    _tap(1)
    _event("onResume")
    assert _title() == "detail:7:0:1"


def test_the_whole_stack_survives_process_death(notes: str) -> None:
    runtime.start(notes, "home", True)
    _tap(1)
    _tap(1)
    saved = _snapshot()["metadata"]["data"]
    runtime.close()
    runtime.start(notes, "home", True, restore=json.dumps(saved))
    assert _title() == "detail:7:1:0"
    _event("onBackRequested")
    assert _title() == "list:7"


def test_only_an_allowed_route_opens_from_outside(notes: str) -> None:
    detail = json.dumps(
        {"fields": {"id": 3}, "route": "nav_app.DetailRoute"}, separators=(",", ":")
    )
    runtime.start(notes, detail, True)
    assert _title() == "detail:3:0:0"
    _event("onBackRequested")
    assert _title() == "list:0"
    runtime.close()
    unknown = json.dumps({"fields": {}, "route": "nav_app.Nowhere"})
    runtime.start(notes, unknown, True)
    assert _title() == "list:0"


def test_a_view_model_that_fails_to_build_leaves_no_work_running(notes: str) -> None:
    runtime.start(notes, "home", True)
    _tap(1)
    saved = json.dumps(_snapshot()["metadata"]["data"])
    runtime.close()
    _settle()
    cleared = sys.modules["nav_app"].CLEARED
    cleared.clear()

    broken = json.dumps({"fields": {"id": 13}, "route": "nav_app.DetailRoute"})
    with pytest.raises(RuntimeError, match="cannot be built"):
        runtime.start(notes, broken, True, restore=saved)
    _settle()
    # The restored detail screen was built, then cleared with the failed session.
    assert cleared == [7]


def test_every_screen_on_the_stack_hears_a_memory_trim(notes: str) -> None:
    runtime.start(notes, "home", True)
    _tap(1)
    _event("onTrimMemory", level="background")
    assert sys.modules["nav_app"].TRIMMED == [
        ("detail", "background"),
        ("list", "background"),
    ]
    _event("onTrimMemory", level="huge")
    assert runtime.fetch_latest_error() != ""


def test_a_back_gesture_can_preview_the_screen_below(notes: str) -> None:
    runtime.start(notes, "home", True)
    assert runtime.fetch_latest("below", -1) == ""  # nothing under the first screen
    _tap(1)
    preview = json.loads(runtime.fetch_latest("below", -1))
    assert (preview["kind"], preview["surface"]) == ("full", "below")
    assert preview["root"]["children"][0]["props"]["text"] == "list:7"
    # A picture of where back leads: the main screen is still the detail.
    assert _title() == "detail:7:0:0"
