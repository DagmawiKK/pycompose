"""On-device module lifecycle through the pure-data Python runtime seam."""

import json
import sys
from pathlib import Path

import pytest

from pycompose.bridge.runtime import RuntimeSession


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
