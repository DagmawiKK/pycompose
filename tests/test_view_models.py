"""View models: intents in, state and effects out, on the session's loop thread."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from pycompose import async_task
from pycompose.app import Intent, StateFlow
from pycompose.bridge import runtime
from pycompose.errors import StateError
from pycompose.ir import emit_ir, to_json
from pycompose.m3 import Button
from pycompose.state import State

APP = """
import asyncio
from pycompose.app import App, Destination, Intent, Toast, ViewModel
from pycompose.m3 import Button, Column, Text
from pycompose.state import AppState, Loaded


class Counter(AppState):
    count: int = 0
    label: str = "ready"
    rows: Loaded[tuple[str, ...]] = ()


class SetCount(Intent):
    count: int


class Load(Intent):
    pass


class Container:
    def __init__(self):
        self.rows = ("a", "b")


class CounterViewModel(ViewModel[Counter]):
    def __init__(self, rows):
        super().__init__(Counter())
        self.source = rows

    def on_intent(self, intent):
        if isinstance(intent, SetCount):
            self.state = self.state.evolve(count=intent.count)
            self.emit(Toast(f"count {intent.count}"))
        elif isinstance(intent, Load):
            self.launch(self.load())

    async def load(self):
        self.state = self.state.evolve(label="loading")
        await asyncio.sleep(0)
        self.state = self.state.evolve(label="loaded", rows=self.source)


def screen(state):
    return Column(children=[
        Text(id="count", text=str(state.count)),
        Text(id="label", text=f"{state.label}:{len(state.rows)}"),
        Button(id="three", text="3", on_click=SetCount(count=3)),
        Button(id="load", text="load", on_click=Load()),
    ])


app = App(
    start=Destination(lambda c, route: CounterViewModel(c.rows), screen),
    container=Container,
)
"""


@pytest.fixture
def counter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    (tmp_path / "counter_app.py").write_text(APP)
    monkeypatch.syspath_prepend(str(tmp_path))
    yield "counter_app:app"
    runtime.close()
    async_task.install_sink(None)
    sys.modules.pop("counter_app", None)


def _snapshot() -> dict:
    return json.loads(runtime.fetch_latest_snapshot())


def _text(snapshot: dict, node_id: str) -> str:
    def find(node: dict) -> str | None:
        if node["id"].endswith(node_id) and "text" in node.get("props", {}):
            return node["props"]["text"]
        for child in node.get("children", []):
            found = find(child)
            if found is not None:
                return found
        return None

    found = find(snapshot["root"])
    assert found is not None, node_id
    return found


def _tap(snapshot: dict, node_id: str) -> None:
    def find(node: dict) -> dict | None:
        if node["id"].endswith(node_id) and "onClick" in node.get("props", {}):
            return node["props"]["onClick"]
        for child in node.get("children", []):
            found = find(child)
            if found is not None:
                return found
        return None

    intent = find(snapshot["root"])
    assert intent is not None, node_id
    runtime.accept_action(json.dumps({**intent, "payload": {}}))


def test_a_control_carries_its_intent_and_the_screen_shows_the_result(
    counter: str,
) -> None:
    runtime.start(counter, "home", True)
    first = _snapshot()
    assert _text(first, "count") == "0"
    _tap(first, "three")
    after = _snapshot()
    assert _text(after, "count") == "3"
    assert after["metadata"]["effects"] == [
        {"kind": "toast", "payload": {"message": "count 3"}}
    ]
    assert runtime.fetch_latest_error() == ""


def test_background_work_signals_one_refresh_and_publishes_its_state(
    counter: str,
) -> None:
    refreshes: list[str] = []
    async_task.install_sink(lambda action, *_: refreshes.append(action))
    runtime.start(counter, "home", True)
    _tap(_snapshot(), "load")
    # The task runs on the loop after the tap; wait for it to finish there.
    runtime._loop_thread().call(lambda: None)
    runtime._loop_thread().call(lambda: None)
    assert refreshes == ["pycompose.refresh"]
    runtime.accept_action(json.dumps({"intent": "pycompose.refresh", "payload": {}}))
    assert _text(_snapshot(), "label") == "loaded:2"


def test_saved_state_restores_and_loaded_fields_are_never_saved(
    counter: str,
) -> None:
    runtime.start(counter, "home", True)
    _tap(_snapshot(), "three")
    saved = _snapshot()["metadata"]["data"]
    assert [entry["state"] for entry in saved["stack"]] == [
        {"count": 3, "label": "ready"}
    ]
    runtime.close()
    runtime.start(counter, "home", True, restore=json.dumps(saved))
    assert _text(_snapshot(), "count") == "3"


def test_an_intent_with_a_field_of_the_wrong_type_is_refused(counter: str) -> None:
    runtime.start(counter, "home", True)
    before = runtime.fetch_latest_snapshot()
    runtime.accept_action(
        json.dumps(
            {"fields": {"count": "3"}, "intent": "counter_app.SetCount", "payload": {}}
        )
    )
    assert runtime.fetch_latest_snapshot() == before
    assert "invalid app action payload" in runtime.fetch_latest_error()


class Open(Intent):
    id: int


class QueryChanged(Intent):
    query: str


def test_an_intent_instance_binds_every_field_and_a_class_binds_none() -> None:
    state = State(
        root=Button(id="b", text="Open", on_click=Open(id=4)),
    )
    wire = json.loads(to_json(emit_ir(state, "1.23.0")))
    assert wire["root"]["props"]["onClick"] == {
        "fields": {"id": 4},
        "intent": f"{__name__}.Open",
    }
    assert wire["metadata"]["intents"][f"{__name__}.Open"] == {
        "payload": {"id": {"required": True, "type": "integer"}}
    }
    partial = QueryChanged.bind()
    assert partial.spec.intent() == {"fields": {}, "intent": f"{__name__}.QueryChanged"}


def test_a_view_model_refuses_state_changes_from_another_thread() -> None:
    from pycompose.app import ViewModel
    from pycompose.state import AppState

    class Box(AppState):
        value: int = 0

    model = ViewModel(Box())
    failure: list[BaseException] = []

    def write() -> None:
        try:
            model.state = Box(value=1)
        except StateError as exc:
            failure.append(exc)

    thread = threading.Thread(target=write)
    thread.start()
    thread.join()
    assert failure
    assert model.state == Box()


def test_a_state_flow_gives_each_collector_the_latest_value() -> None:
    async def run() -> list[int]:
        flow = StateFlow(0)
        seen: list[int] = []

        async def collect() -> None:
            async for value in flow:
                seen.append(value)
                if value == 3:
                    return

        task = asyncio.get_running_loop().create_task(collect())
        await asyncio.sleep(0)
        flow.value = 1
        flow.value = 2
        flow.value = 2
        flow.value = 3
        await task
        return seen

    # Conflated: the collector saw the start and the latest, never a backlog.
    assert asyncio.run(run()) == [0, 3]
