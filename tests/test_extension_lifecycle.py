"""Owned extensions across successful reload, failed reload and worker teardown."""

import json
import queue
import sys
from pathlib import Path

import pytest

from pycompose import async_task
from pycompose.bridge.runtime import RuntimeSession
from pycompose.errors import StateError

SOURCE = """from types import SimpleNamespace
from threading import Event
from pycompose import action
from pycompose.extensions import Resource
from pycompose.m3 import Text
from pycompose.state import Actions, App, State
created = []
def factory():
    closed = Event()
    resource = Resource(lambda: None, close=lambda _: closed.set())
    made = SimpleNamespace(resource=resource, closed=closed)
    created.append(made)
    return made
@action
def arrived(state: State, value: str) -> State:
    return State(root=Text(id="text", text=value), version=state.version + 1)
@action
def launch(state: State, value: str, *, container) -> State:
    container.resource.submit(lambda _: {"value": value}, success=arrived)
    return state
actions = Actions(arrived, launch)
app = App(view=lambda _: State(root=Text(id="text", text="idle")), container=factory)
"""


@pytest.mark.parametrize("successful", [False, True])
def test_reload_rejects_old_completions_only_when_the_candidate_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    successful: bool,
) -> None:
    path = tmp_path / "extension_app.py"
    path.write_text(SOURCE)
    monkeypatch.syspath_prepend(str(tmp_path))
    pending: queue.Queue[str] = queue.Queue()
    async_task.install_sink(
        lambda aid, payload: pending.put(
            json.dumps({"actionId": aid, "payload": json.loads(payload)})
        )
    )
    session = RuntimeSession("extension_app:app", "home", debug=True)
    container = sys.modules["extension_app"].created[0]
    try:
        session.accept_action(
            '{"actionId":"extension_app.launch","payload":{"value":"old"}}'
        )
        queued = pending.get(timeout=3)
        path.write_text(
            SOURCE if successful else 'raise RuntimeError("candidate failed")\n'
        )
        assert session.reload("home") is successful
        session.accept_action(queued)
        text = json.loads(session.snapshot())["root"]["props"]["text"]
        assert text == ("idle" if successful else "old")
        session.accept_action(
            '{"actionId":"extension_app.launch","payload":{"value":"new"}}'
        )
        session.accept_action(pending.get(timeout=3))
        assert json.loads(session.snapshot())["root"]["props"]["text"] == "new"
    finally:
        session.close()
        assert container.closed.wait(3)
        sys.modules.pop("extension_app", None)
        async_task.install_sink(None)
    with pytest.raises(StateError, match="closed"):
        container.resource.submit(lambda _: None)
