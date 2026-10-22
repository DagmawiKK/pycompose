"""ADR-0018 pull envelopes: the bridge's serial window and full/patch choice."""

import copy
import json
import sys
from dataclasses import replace
from pathlib import Path
from threading import Thread
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pycompose.bridge import BridgeSurface, runtime
from pycompose.bridge.api import PATCH_WINDOW
from pycompose.bridge.runtime import RuntimeSession
from pycompose.core import Node, Props
from pycompose.errors import BridgeError
from pycompose.state import Actions, State, Store


def _text(key: str, text: str) -> Node:
    return Node(id=key, type="Text", props=Props({"text": text}))


def _column(key: str, *children: Node) -> Node:
    return Node(id=key, type="Column", props=Props({}), children=children)


def _rows(*texts: str) -> Node:
    return _column("list", *(_text(f"row{i}", text) for i, text in enumerate(texts)))


def _bridge(screens: list[Node], **options: Any) -> BridgeSurface:
    """Serve ``screens[0]``; ``increment`` with ``by=n`` shows ``screens[n]``."""
    actions = Actions()
    actions.register(
        "increment", lambda state, payload: replace(state, root=screens[payload["by"]])
    )
    return BridgeSurface(Store(State(root=screens[0])), actions, **options)


def _show(bridge: BridgeSurface, index: int) -> None:
    bridge.accept_action(
        json.dumps({"actionId": "increment", "payload": {"by": index}})
    )


def _pull(bridge: BridgeSurface, base: Any) -> dict[str, Any]:
    envelope = bridge.expose_latest_envelope(base)
    assert envelope is not None
    decoded: dict[str, Any] = json.loads(envelope)
    return decoded


def _root(bridge: BridgeSurface) -> dict[str, Any]:
    snapshot = bridge.expose_latest_snapshot()
    assert snapshot is not None
    root: dict[str, Any] = json.loads(snapshot)["root"]
    return root


def _apply(root: dict[str, Any], ops: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply envelope ops by node id, as a host holding ``root`` would."""
    tree = copy.deepcopy(root)
    for op in ops:
        parent, index, node = None, -1, tree
        pending: list[tuple[dict[str, Any] | None, int, dict[str, Any]]] = [
            (None, -1, tree)
        ]
        while pending:
            parent, index, node = pending.pop()
            if node["id"] == op["id"]:
                break
            pending.extend(
                (node, position, child)
                for position, child in enumerate(node.get("children", ()))
            )
        else:
            pytest.fail(f"op names a node the host does not hold: {op['id']}")
        if op["op"] == "setProp":
            node.setdefault("props", {})[op["prop"]] = op["value"]
        elif parent is None:
            tree = copy.deepcopy(op["payload"])
        else:
            parent["children"][index] = copy.deepcopy(op["payload"])
    return tree


def test_the_first_pull_is_the_snapshot_plus_kind_and_serial() -> None:
    bridge = _bridge([_rows("a", "b")])
    envelope = _pull(bridge, 0)
    assert envelope.pop("kind") == "full"
    assert envelope.pop("serial") == 1
    assert envelope == json.loads(bridge.expose_latest_snapshot() or "")


def test_a_prop_change_against_the_held_base_is_one_set_prop() -> None:
    bridge = _bridge([_rows("a", "b", "c"), _rows("a", "changed", "c")])
    base = _root(bridge)
    _show(bridge, 1)
    envelope = _pull(bridge, 1)
    assert (envelope["kind"], envelope["baseSerial"], envelope["serial"]) == (
        "patch",
        1,
        2,
    )
    [op] = envelope["ops"]
    assert (op["op"], op["prop"], op["value"]) == ("setProp", "text", "changed")
    assert _apply(base, envelope["ops"]) == _root(bridge)


def test_an_unchanged_state_keeps_its_serial_and_pulls_an_empty_patch() -> None:
    bridge = _bridge([_rows("a")])
    _show(bridge, 0)
    assert bridge.serial == 1
    envelope = _pull(bridge, 1)
    assert (envelope["kind"], envelope["baseSerial"], envelope["serial"]) == (
        "patch",
        1,
        1,
    )
    assert envelope["ops"] == []


def test_replacing_the_root_ships_the_full_snapshot() -> None:
    bridge = _bridge([_rows("a", "b"), _rows("a", "b", "appended")])
    _show(bridge, 1)
    envelope = _pull(bridge, 1)
    assert (envelope["kind"], envelope["serial"]) == ("full", 2)
    assert envelope["root"] == _root(bridge)


def test_a_nested_structural_change_ships_only_that_subtree() -> None:
    before = _column("screen", _text("title", "Notes"), _rows("a", "b"))
    after = _column("screen", _text("title", "Notes"), _rows("a", "b", "c"))
    bridge = _bridge([before, after])
    base = _root(bridge)
    _show(bridge, 1)
    envelope = _pull(bridge, 1)
    assert envelope["kind"] == "patch"
    [op] = envelope["ops"]
    assert op["op"] == "replaceSubtree"
    assert op["id"] != base["id"]
    assert _apply(base, envelope["ops"]) == _root(bridge)


def test_a_base_older_than_the_window_pulls_full() -> None:
    screens = [_rows(str(step)) for step in range(PATCH_WINDOW + 2)]
    bridge = _bridge(screens)
    for step in range(1, len(screens)):
        _show(bridge, step)
    latest = bridge.serial
    assert latest == PATCH_WINDOW + 2
    assert _pull(bridge, 1)["kind"] == "full"
    assert _pull(bridge, latest - PATCH_WINDOW + 1)["kind"] == "patch"
    assert _pull(bridge, latest - PATCH_WINDOW)["kind"] == "full"


@pytest.mark.parametrize("base", [0, -1, 99, True, "1", None, 1.0])
def test_a_base_the_bridge_does_not_keep_pulls_full(base: object) -> None:
    bridge = _bridge([_rows("a")])
    envelope = _pull(bridge, base)
    assert (envelope["kind"], envelope["serial"]) == ("full", 1)


def test_metadata_rides_every_patch_envelope() -> None:
    actions = Actions()
    actions.register(
        "increment",
        lambda state, payload: replace(
            state, root=_rows(str(payload["by"])), data={"count": payload["by"]}
        ),
    )
    bridge = BridgeSurface(Store(State(root=_rows("0"), data={"count": 0})), actions)
    bridge.accept_action('{"actionId":"increment","payload":{"by":2}}')
    envelope = _pull(bridge, 1)
    assert envelope["kind"] == "patch"
    assert envelope["metadata"]["data"] == {"count": 2}


def test_an_off_worker_pull_is_refused_as_data() -> None:
    bridge = _bridge([_rows("a")])
    pulled: list[str | None] = []
    thread = Thread(target=lambda: pulled.append(bridge.expose_latest_envelope(0)))
    thread.start()
    thread.join()
    assert pulled == [None]
    assert "worker contract violation" in bridge.expose_latest_error()


def test_numbering_starts_at_first_serial() -> None:
    bridge = _bridge([_rows("a"), _rows("b")], first_serial=8)
    assert _pull(bridge, 0)["serial"] == 8
    _show(bridge, 1)
    assert _pull(bridge, 8)["serial"] == 9


@pytest.mark.parametrize("first_serial", [0, -3, True])
def test_a_non_positive_first_serial_is_refused(first_serial: int) -> None:
    with pytest.raises(BridgeError, match="first_serial"):
        _bridge([_rows("a")], first_serial=first_serial)


@settings(max_examples=60, deadline=None)
@given(
    st.lists(
        st.tuples(st.integers(min_value=0, max_value=3), st.text(max_size=6)),
        max_size=8,
    )
)
def test_applying_each_pull_rebuilds_the_published_root(
    edits: list[tuple[int, str]],
) -> None:
    texts = ["a", "b", "c", "d"]
    screens = [_rows(*texts)]
    bridge = _bridge(screens)
    first = _pull(bridge, 0)
    held, held_serial = first["root"], first["serial"]
    for row, text in edits:
        texts[row] = text
        screens.append(_rows(*texts))
        _show(bridge, len(screens) - 1)
        envelope = _pull(bridge, held_serial)
        if envelope["kind"] == "patch":
            assert envelope["baseSerial"] == held_serial
            held = _apply(held, envelope["ops"])
        else:
            held = envelope["root"]
        held_serial = envelope["serial"]
        assert held == _root(bridge)


def test_a_debug_reload_continues_serials_so_old_bases_pull_full(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = tmp_path / "envelope_app.py"
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
        session = RuntimeSession("envelope_app:app", "home", debug=True)
        assert json.loads(session.envelope(0))["serial"] == 1
        session.accept_action('{"actionId":"increment","payload":{}}')
        assert json.loads(session.envelope(1))["kind"] == "patch"
        module.write_text(module.read_text().replace("shell.route", '"reloaded"'))
        assert session.reload("home") is True
        envelope = json.loads(session.envelope(2))
        assert (envelope["kind"], envelope["serial"]) == ("full", 3)
        assert envelope["root"]["props"]["text"] == "reloaded"
    finally:
        sys.modules.pop("envelope_app", None)


def test_the_module_pull_is_empty_before_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime, "_session", None)
    assert runtime.fetch_latest_envelope(0) == ""
