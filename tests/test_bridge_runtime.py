"""On-device module lifecycle through the pure-data Python runtime seam."""

import json
import sys
from pathlib import Path

import pytest

from pycompose.bridge.runtime import RuntimeSession
from pycompose.errors import BridgeError


def test_runtime_build_action_reload_and_bad_reload_retains_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = tmp_path / "device_app.py"
    module.write_text("""from pycompose.m3 import Text
from pycompose.state import State, Actions
actions = Actions()
def build(*, route="home"):
    return State(root=Text(id="text", text=route))
actions.register("increment",
    lambda state, _: State(root=Text(id="text", text="changed")))
""")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        session = RuntimeSession("device_app:build", "restored", debug=True)
        assert json.loads(session.snapshot())["root"]["props"]["text"] == "restored"
        session.accept_action('{"actionId":"increment","payload":{}}')
        assert json.loads(session.snapshot())["root"]["props"]["text"] == "changed"
        module.write_text("""from pycompose.m3 import Text
from pycompose.state import State
def build(*, route="home"):
    return State(root=Text(id="text", text="reloaded"))
""")
        session.reload("restored")
        assert json.loads(session.snapshot())["root"]["props"]["text"] == "reloaded"
        previous = session.snapshot()
        module.write_text('raise RuntimeError("broken app")\n')
        session.reload("restored")
        assert session.snapshot() == previous
        assert "broken app" in session.error()
    finally:
        sys.modules.pop("device_app", None)


def test_saved_bytes_reach_build_and_survive_a_debug_reload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = tmp_path / "restore_app.py"
    module.write_text("""from pycompose.m3 import Text
from pycompose.state import State
def build(*, restore=""):
    return State(root=Text(id="text", text=restore or "fresh"), data={"seen": restore})
""")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        saved = '{"tasks":[{"id":1}]}'
        session = RuntimeSession("restore_app:build", "home", debug=True, restore=saved)
        assert json.loads(session.snapshot())["root"]["props"]["text"] == saved
        session.reload("home", restore=saved)
        assert json.loads(session.snapshot())["root"]["props"]["text"] == saved
    finally:
        sys.modules.pop("restore_app", None)


def test_an_app_that_declares_no_restore_parameter_still_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = tmp_path / "plain_app.py"
    module.write_text("""from pycompose.m3 import Text
from pycompose.state import State
def build(*, route="home"):
    return State(root=Text(id="text", text=route))
""")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        session = RuntimeSession("plain_app:build", "home", debug=True, restore="{}")
        assert json.loads(session.snapshot())["root"]["props"]["text"] == "home"
    finally:
        sys.modules.pop("plain_app", None)


def test_session_calls_the_container_factory_once_and_hands_it_to_every_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = tmp_path / "container_app.py"
    module.write_text("""from pycompose.m3 import Text
from pycompose.state import State
class Container:
    def __init__(self):
        self.label = "first"
built = []
def container():
    built.append(1)
    return Container()
def build(*, container=None):
    built.append(container)
    return State(root=Text(id="text", text=container.label))
""")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        session = RuntimeSession("container_app:build", "home", debug=True)
        app = sys.modules["container_app"]
        shared = app.built[-1]
        assert shared.label == "first"
        assert len(app.built) == 2  # factory call, then the container handed to build
        module.write_text("""from pycompose.m3 import Text
from pycompose.state import State
class Container:
    def __init__(self):
        self.label = "second"
built = []
def container():
    built.append(1)
    return Container()
def build(*, container=None):
    built.append(container)
    container.label = "reloaded"
    return State(root=Text(id="text", text=container.label))
""")
        session.reload("home")
        assert json.loads(session.snapshot())["root"]["props"]["text"] == "reloaded"
        reloaded = sys.modules["container_app"]
        assert reloaded.built[-1] is shared
        # Only build appended: the fresh module's factory was never called.
        assert len(reloaded.built) == 1
        assert shared.label == "reloaded"
    finally:
        sys.modules.pop("container_app", None)


def test_a_failed_reload_keeps_the_original_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = tmp_path / "rollback_container_app.py"
    module.write_text("""from pycompose.m3 import Text
from pycompose.state import State
calls = []
def container():
    return object()
def build(*, container=None):
    calls.append(container)
    return State(root=Text(id="text", text="original"))
""")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        session = RuntimeSession("rollback_container_app:build", "home", debug=True)
        sys.modules["rollback_container_app"].calls.clear()
        module.write_text('raise RuntimeError("broken app")\n')
        session.reload("home")
        assert "broken app" in session.error()
        module.write_text("""from pycompose.m3 import Text
from pycompose.state import State
calls = []
def container():
    return object()
def build(*, container=None):
    calls.append(container)
    return State(root=Text(id="text", text="recovered"))
""")
        module.write_text("""from pycompose.m3 import Text
from pycompose.state import State
calls = []
def container():
    return object()
def build(*, container=None):
    calls.append(container)
    return State(root=Text(id="text", text="recovered"))
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
from pycompose.state import State
container = object()
def build():
    return State(root=Text(id="text", text="hi"))
""")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        with pytest.raises(BridgeError, match="zero-argument callable"):
            RuntimeSession("bad_container_app:build", "home", debug=True)
    finally:
        sys.modules.pop("bad_container_app", None)


def test_failed_reload_restores_the_app_module_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = tmp_path / "device_helper.py"
    helper.write_text('label = "original"\n')
    app = tmp_path / "rollback_app.py"
    app.write_text("""from pycompose.m3 import Text
from pycompose.state import State, Actions
import device_helper
actions = Actions()
def build():
    return State(root=Text(id="text", text=device_helper.label))
def increment(state, payload):
    import device_helper
    return State(root=Text(id="text", text=device_helper.label))
actions.register("increment", increment)
""")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        session = RuntimeSession("rollback_app:build", "home", debug=True)
        helper.write_text('label = "failed candidate"\n')
        app.write_text('import device_helper\nraise RuntimeError("broken")\n')
        session.reload("home")
        session.accept_action('{"actionId":"increment","payload":{}}')
        assert json.loads(session.snapshot())["root"]["props"]["text"] == "original"
    finally:
        sys.modules.pop("rollback_app", None)
        sys.modules.pop("device_helper", None)
