"""On-device module lifecycle through the pure-data Python runtime seam."""

import json
import sys
from pathlib import Path

import pytest

from pycompose.bridge.runtime import RuntimeSession
from pycompose.errors import BridgeError, StateError


def test_runtime_build_action_reload_and_bad_reload_retains_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = tmp_path / "device_app.py"
    module.write_text("""from pycompose.m3 import Text
from pycompose.state import Actions, App, AppState, State
class Shell(AppState):
    route: str = "home"
actions = Actions()
def view(shell):
    return Text(id="text", text=shell.route)
app = App(state=Shell, view=view, route="route")
actions.register("increment",
    lambda state, _: State(root=Text(id="text", text="changed")))
""")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        session = RuntimeSession("device_app:app", "restored", debug=True)
        assert json.loads(session.snapshot())["root"]["props"]["text"] == "restored"
        session.accept_action('{"actionId":"increment","payload":{}}')
        assert json.loads(session.snapshot())["root"]["props"]["text"] == "changed"
        module.write_text("""from pycompose.m3 import Text
from pycompose.state import App, AppState
class Shell(AppState):
    route: str = "home"
def view(shell):
    return Text(id="text", text="reloaded")
app = App(state=Shell, view=view, route="route")
""")
        assert session.reload("restored") is True
        assert json.loads(session.snapshot())["root"]["props"]["text"] == "reloaded"
        previous = session.snapshot()
        module.write_text('raise RuntimeError("broken app")\n')
        assert session.reload("restored") is False
        assert session.snapshot() == previous
        assert "broken app" in session.error()
    finally:
        sys.modules.pop("device_app", None)


def test_saved_bytes_reach_the_view_and_survive_a_debug_reload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = tmp_path / "restore_app.py"
    module.write_text("""from pycompose.m3 import Text
from pycompose.state import App, State
def view(restore):
    return State(root=Text(id="text", text=restore or "fresh"), data={"seen": restore})
app = App(view=view)
""")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        saved = '{"tasks":[{"id":1}]}'
        session = RuntimeSession("restore_app:app", "home", debug=True, restore=saved)
        assert json.loads(session.snapshot())["root"]["props"]["text"] == saved
        session.reload("home", restore=saved)
        assert json.loads(session.snapshot())["root"]["props"]["text"] == saved
    finally:
        sys.modules.pop("restore_app", None)


def test_an_app_that_ignores_the_saved_bytes_still_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = tmp_path / "plain_app.py"
    module.write_text("""from pycompose.m3 import Text
from pycompose.state import App, State
def view(restore):
    return State(root=Text(id="text", text="home"))
app = App(view=view)
""")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        session = RuntimeSession("plain_app:app", "home", debug=True, restore="{}")
        assert json.loads(session.snapshot())["root"]["props"]["text"] == "home"
    finally:
        sys.modules.pop("plain_app", None)


def test_session_calls_the_container_factory_once_and_keeps_it_across_reloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = tmp_path / "container_app.py"
    module.write_text("""from pycompose import context
from pycompose.m3 import Text
from pycompose.state import App, State
class Container:
    def __init__(self):
        self.label = "first"
built = []
def container():
    made = Container()
    built.append(made)
    return made
def view(restore):
    return State(root=Text(id="text", text=context().container.label))
app = App(view=view, container=container)
""")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        session = RuntimeSession("container_app:app", "home", debug=True)
        app_module = sys.modules["container_app"]
        shared = app_module.built[0]
        assert len(app_module.built) == 1  # only the factory ran, once
        module.write_text("""from pycompose import context
from pycompose.m3 import Text
from pycompose.state import App, State
class Container:
    def __init__(self):
        self.label = "second"
built = []
def container():
    made = Container()
    built.append(made)
    return made
def view(restore):
    context().container.label = "reloaded"
    return State(root=Text(id="text", text=context().container.label))
app = App(view=view, container=container)
""")
        session.reload("home")
        assert json.loads(session.snapshot())["root"]["props"]["text"] == "reloaded"
        reloaded = sys.modules["container_app"]
        # The fresh module's factory was never called: the session retained
        # the container built before the reload.
        assert reloaded.built == []
        assert shared.label == "reloaded"
    finally:
        sys.modules.pop("container_app", None)


def test_a_failed_reload_keeps_the_original_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = tmp_path / "rollback_container_app.py"
    module.write_text("""from pycompose import context
from pycompose.m3 import Text
from pycompose.state import App, State
calls = []
def container():
    return object()
def view(restore):
    calls.append(context().container)
    return State(root=Text(id="text", text="original"))
app = App(view=view, container=container)
""")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        session = RuntimeSession("rollback_container_app:app", "home", debug=True)
        sys.modules["rollback_container_app"].calls.clear()
        module.write_text('raise RuntimeError("broken app")\n')
        session.reload("home")
        assert "broken app" in session.error()
        module.write_text("""from pycompose import context
from pycompose.m3 import Text
from pycompose.state import App, State
calls = []
def container():
    return object()
def view(restore):
    calls.append(context().container)
    return State(root=Text(id="text", text="recovered"))
app = App(view=view, container=container)
""")
        session.reload("home")
        assert json.loads(session.snapshot())["root"]["props"]["text"] == "recovered"
        assert len(sys.modules["rollback_container_app"].calls) == 1
    finally:
        sys.modules.pop("rollback_container_app", None)


def test_a_non_callable_container_declaration_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = tmp_path / "bad_container_app.py"
    module.write_text("""from pycompose.m3 import Text
from pycompose.state import App, State
def view(restore):
    return State(root=Text(id="text", text="hi"))
app = App(view=view, container=object())
""")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        with pytest.raises(StateError, match="zero-argument callable"):
            RuntimeSession("bad_container_app:app", "home", debug=True)
    finally:
        sys.modules.pop("bad_container_app", None)


def test_entrypoint_that_names_no_app_export_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = tmp_path / "no_export_app.py"
    module.write_text('label = "not an app"\n')
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        with pytest.raises(BridgeError, match="App export"):
            RuntimeSession("no_export_app:build", "home", debug=True)
    finally:
        sys.modules.pop("no_export_app", None)


def test_failed_reload_restores_the_app_module_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = tmp_path / "device_helper.py"
    helper.write_text('label = "original"\n')
    app = tmp_path / "rollback_app.py"
    app.write_text("""from pycompose.m3 import Text
from pycompose.state import Actions, App, State
import device_helper
actions = Actions()
def view(restore):
    return State(root=Text(id="text", text=device_helper.label))
app = App(view=view)
def increment(state, payload):
    import device_helper
    return State(root=Text(id="text", text=device_helper.label))
actions.register("increment", increment)
""")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        session = RuntimeSession("rollback_app:app", "home", debug=True)
        helper.write_text('label = "failed candidate"\n')
        app.write_text('import device_helper\nraise RuntimeError("broken")\n')
        session.reload("home")
        session.accept_action('{"actionId":"increment","payload":{}}')
        assert json.loads(session.snapshot())["root"]["props"]["text"] == "original"
    finally:
        sys.modules.pop("rollback_app", None)
        sys.modules.pop("device_helper", None)


def test_a_reloaded_session_answers_an_old_serial_with_the_whole_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = tmp_path / "pull_app.py"
    source = """from pycompose.m3 import Text
from pycompose.state import Actions, App, AppState, State
class Shell(AppState):
    route: str = "home"
actions = Actions()
def view(shell):
    return Text(id="text", text=%r)
app = App(state=Shell, view=view, route="route")
actions.register("increment",
    lambda state, _: State(root=Text(id="text", text="changed")))
"""
    module.write_text(source % "first")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        session = RuntimeSession("pull_app:app", "home", debug=True)
        first = json.loads(session.envelope("main", -1))
        assert first["kind"] == "full"
        session.accept_action('{"actionId":"increment","payload":{}}')
        patch = json.loads(session.envelope("main", first["serial"]))
        assert (patch["kind"], patch["baseSerial"]) == ("patch", first["serial"])

        module.write_text(source % "reloaded")
        assert session.reload("home") is True
        assert json.loads(session.envelope("main", patch["serial"]))["kind"] == "full"
    finally:
        sys.modules.pop("pull_app", None)
