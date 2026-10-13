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
