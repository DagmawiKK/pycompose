"""Host-owned worker calls through the pure-data bridge seam."""

import json
import logging
from collections.abc import Mapping
from dataclasses import replace
from threading import Thread

import pytest

from pycompose.bridge import BridgeSurface
from pycompose.bridge.types import IncrementPayload, SubmitPayload
from pycompose.contract.catalog import SCHEMA_VERSION
from pycompose.core import Node, Props
from pycompose.errors import SchemaError
from pycompose.state import Actions, State, Store
from pycompose.utils.json_canonical import FrozenJsonValue


def test_action_handler_publishes_the_next_canonical_snapshot() -> None:
    store = Store(State(root=Node(id="title", type="Text", props=Props({"text": "0"}))))
    actions = Actions()

    def increment(state: State, payload: dict[str, int]) -> State:
        return replace(
            state,
            root=Node(
                id="title",
                type="Text",
                props=Props(
                    {"text": str(int(state.root.props.values["text"]) + payload["by"])}
                ),
            ),
        )

    actions.register("increment", increment)
    bridge = BridgeSurface(store, actions)
    initial = bridge.expose_latest_snapshot()
    assert json.loads(initial)["root"]["props"]["text"] == "0"
    assert bridge.accept_action('{"intent":"increment","payload":{"by":2}}') is None
    assert bridge.expose_latest_snapshot() == (
        '{"root":{"id":"root","props":{"text":"2"},"type":"Text"},'
        '"schemaVersion":"' + SCHEMA_VERSION + '","version":"0.1.0"}'
    )
    assert store.value.root.props.values["text"] == "2"


def test_fifo_actions_apply_payload_defaults_and_preserve_order() -> None:
    store = Store(State(root=Node(id="value", type="Text", props={"text": "start"})))
    actions = Actions()
    calls: list[object] = []

    def append(state: State, payload: Mapping[str, FrozenJsonValue]) -> State:
        calls.append(payload["by"])
        return replace(
            state,
            root=Node(
                id="value",
                type="Text",
                props={"text": f'{state.root.props.values["text"]},{payload["by"]}'},
            ),
        )

    actions.register("increment", append)
    bridge = BridgeSurface(store, actions)
    for message in (
        '{"intent":"increment","payload":{"by":3}}',
        '{"intent":"increment"}',
        '{"intent":"increment","payload":{"by":2}}',
    ):
        bridge.accept_action(message)
    assert calls == [3, 1, 2]
    assert (
        json.loads(bridge.expose_latest_snapshot())["root"]["props"]["text"]
        == "start,3,1,2"
    )


@pytest.mark.parametrize(
    "message",
    [
        "not json",
        "[]",
        "null",
        "{}",
        '{"intent":"missing"}',
        '{"intent":"increment","payload":null}',
        '{"intent":"increment","payload":{"by":true}}',
        '{"intent":"increment","payload":{"by":1.5}}',
        '{"intent":"increment","payload":{"by":NaN}}',
        '{"intent":"increment","payload":{"extra":1}}',
        '{"intent":"submit","payload":{}}',
        '{"intent":"increment","extra":1}',
        '{"intent":"increment","intent":"submit","payload":{"email":"a"}}',
        '{"intent":"increment","payload":{"by":2,"by":3}}',
    ],
)
@pytest.mark.parametrize("debug", [True, False])
def test_bad_actions_are_ignored_with_debug_or_release_diagnostics(
    message: str, debug: bool, caplog: pytest.LogCaptureFixture
) -> None:
    store = Store(
        State(root=Node(id="value", type="Text", props={"text": "unchanged"}))
    )
    actions = Actions()
    calls: list[str] = []

    def handler(state: State, _payload: object) -> State:
        calls.append("called")
        return state

    actions.register("increment", handler)
    actions.register("submit", handler)
    bridge = BridgeSurface(store, actions, debug=debug)
    before = bridge.expose_latest_snapshot()
    original = store.value
    bridge.accept_action(message)
    assert calls == []
    assert store.value is original
    assert bridge.expose_latest_snapshot() is before
    assert caplog.records[-1].levelno == (logging.ERROR if debug else logging.WARNING)
    assert bool(caplog.records[-1].exc_info) is debug


def test_no_op_preserves_snapshot_identity_and_store() -> None:
    original = State(root=Node(id="value", type="Text", props={"text": "unchanged"}))
    store = Store(original)
    actions = Actions()
    actions.register("increment", lambda state, _payload: replace(state))
    bridge = BridgeSurface(store, actions)
    before = bridge.expose_latest_snapshot()
    bridge.accept_action('{"intent":"increment"}')
    assert store.value is original
    assert bridge.expose_latest_snapshot() is before


def test_actions_from_another_thread_are_not_dispatched(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = Store(State(root=Node(id="value", type="Text", props={"text": "start"})))
    calls: list[str] = []
    actions = Actions()

    def handler(state: State, _payload: object) -> State:
        calls.append("called")
        return state

    actions.register("increment", handler)
    bridge = BridgeSurface(store, actions)
    thread = Thread(target=bridge.accept_action, args=('{"intent":"increment"}',))
    thread.start()
    thread.join()
    assert calls == []
    assert "worker" in caplog.text


def test_registry_generated_payload_contracts_work_through_the_bridge() -> None:
    increment: IncrementPayload = {}
    submit: SubmitPayload = {"email": "ada@example.com"}
    seen: list[object] = []
    actions = Actions()

    def handler(state: State, payload: object) -> State:
        seen.append(payload)
        return state

    actions.register("increment", handler)
    actions.register("submit", handler)
    bridge = BridgeSurface(
        Store(State(root=Node(id="text", type="Text", props={"text": "hi"}))), actions
    )
    bridge.accept_action(json.dumps({"intent": "increment", "payload": increment}))
    bridge.accept_action(json.dumps({"intent": "submit", "payload": submit}))
    assert seen == [{"by": 1}, {"email": "ada@example.com"}]


@pytest.mark.parametrize("debug", [True, False])
def test_handler_failure_preserves_state_and_allows_the_next_action(
    debug: bool, caplog: pytest.LogCaptureFixture
) -> None:
    original = State(root=Node(id="value", type="Text", props={"text": "old"}))
    store = Store(original)
    actions = Actions()

    def fail(_state: State, _payload: object) -> State:
        raise RuntimeError("handler failed")

    actions.register("increment", fail)
    bridge = BridgeSurface(store, actions, debug=debug)
    before = bridge.expose_latest_snapshot()
    bridge.accept_action('{"intent":"increment"}')
    assert store.value is original
    assert bridge.expose_latest_snapshot() is before
    assert "handler failed" in caplog.text
    actions.register(
        "increment",
        lambda state, _payload: replace(
            state, root=Node(id="value", type="Text", props={"text": "next"})
        ),
    )
    bridge.accept_action('{"intent":"increment"}')
    assert (
        json.loads(bridge.expose_latest_snapshot())["root"]["props"]["text"] == "next"
    )


@pytest.mark.parametrize("debug", [True, False])
def test_invalid_next_snapshot_never_commits_partial_state(debug: bool) -> None:
    original = State(root=Node(id="value", type="Text", props={"text": "old"}))
    store = Store(original)
    actions = Actions()
    actions.register(
        "increment",
        lambda state, _payload: replace(state, root=Node(id="value", type="Missing")),
    )
    bridge = BridgeSurface(store, actions, debug=debug)
    before = bridge.expose_latest_snapshot()
    bridge.accept_action('{"intent":"increment"}')
    assert store.value is original
    assert bridge.expose_latest_snapshot() is before


def test_reentrant_action_is_rejected_without_disturbing_the_outer_transition(
    caplog: pytest.LogCaptureFixture,
) -> None:
    actions = Actions()
    calls: list[str] = []
    store = Store(State(root=Node(id="value", type="Text", props={"text": "old"})))

    def handler(state: State, _payload: object) -> State:
        calls.append("outer")
        bridge.accept_action('{"intent":"increment"}')
        return replace(
            state, root=Node(id="value", type="Text", props={"text": "done"})
        )

    actions.register("increment", handler)
    bridge = BridgeSurface(store, actions)
    bridge.accept_action('{"intent":"increment"}')
    assert calls == ["outer"]
    assert "reentrant" in caplog.text
    assert (
        json.loads(bridge.expose_latest_snapshot())["root"]["props"]["text"] == "done"
    )


def test_handler_payload_is_immutable() -> None:
    actions = Actions()
    seen: list[Mapping[str, FrozenJsonValue]] = []

    def handler(state: State, payload: Mapping[str, FrozenJsonValue]) -> State:
        seen.append(payload)
        with pytest.raises(TypeError):
            payload["by"] = 5  # type: ignore[index]
        return state

    actions.register("increment", handler)
    bridge = BridgeSurface(
        Store(State(root=Node(id="value", type="Text", props={"text": "hi"}))), actions
    )
    bridge.accept_action('{"intent":"increment"}')
    assert seen == [{"by": 1}]


def test_deep_snapshot_transition_is_not_limited_by_state_equality() -> None:
    def nested(text: str) -> Node:
        node = Node(id="leaf", type="Text", props={"text": text})
        for _ in range(1200):
            node = Node(id="child", type="Column", children=(node,))
        return node

    store = Store(State(root=nested("old")))
    actions = Actions()
    actions.register(
        "increment", lambda state, _payload: replace(state, root=nested("next"))
    )
    bridge = BridgeSurface(store, actions)
    bridge.accept_action('{"intent":"increment"}')
    assert '"text":"next"' in bridge.expose_latest_snapshot()


@pytest.mark.parametrize("debug", [True, False])
def test_version_mismatch_fails_at_bridge_configuration(debug: bool) -> None:
    with pytest.raises(SchemaError):
        BridgeSurface(
            Store(State(root=Node(id="text", type="Text", props={"text": "hi"}))),
            Actions(),
            schema_version="2.0.0",
            debug=debug,
        )


@pytest.mark.parametrize("debug", [True, False])
def test_invalid_initial_snapshot_is_unavailable_and_logged(
    debug: bool, caplog: pytest.LogCaptureFixture
) -> None:
    bridge = BridgeSurface(
        Store(State(root=Node(id="text", type="Missing"))), Actions(), debug=debug
    )
    assert bridge.expose_latest_snapshot() is None
    assert caplog.records


def _apply_ops(
    node: dict[str, object], ops: list[dict[str, object]]
) -> dict[str, object]:
    """Apply envelope ops to a plain JSON tree, the way the host does: by index."""

    def rebuild(
        current: dict[str, object], op: dict[str, object], at: list[int]
    ) -> dict[str, object]:
        if not at:
            assert current["id"] == op["id"]
            if op["op"] == "replaceSubtree":
                return op["payload"]  # type: ignore[return-value]
            props = {**current["props"], op["prop"]: op["value"]}  # type: ignore[dict-item]
            return {**current, "props": props}
        children = list(current["children"])  # type: ignore[call-overload]
        children[at[0]] = rebuild(children[at[0]], op, at[1:])
        return {**current, "children": children}

    for op in ops:
        node = rebuild(node, op, list(op["at"]))  # type: ignore[call-overload]
    return node


def _counter_bridge(*, debug: bool = True) -> BridgeSurface:
    def row(text: str) -> Node:
        return Node(id="count", type="Text", props=Props({"text": text}))

    def screen(text: str) -> Node:
        title = Node(id="title", type="Text", props=Props({"text": "Counter"}))
        return Node(
            id="screen", type="Column", props=Props({}), children=(title, row(text))
        )

    actions = Actions()
    actions.register(
        "increment",
        lambda state, payload: replace(state, root=screen(str(payload["by"]))),
    )
    return BridgeSurface(Store(State(root=screen("0"))), actions, debug=debug)


def test_a_pull_from_a_known_base_is_a_patch_that_rebuilds_the_latest() -> None:
    bridge = _counter_bridge()
    first = json.loads(bridge.expose_envelope(-1))
    assert first["kind"] == "full"

    bridge.accept_action('{"intent":"increment","payload":{"by":2}}')
    patch = json.loads(bridge.expose_envelope(first["serial"]))

    assert (patch["kind"], patch["baseSerial"]) == ("patch", first["serial"])
    assert [(op["op"], op["id"]) for op in patch["ops"]] == [("setProp", "root.count")]
    latest = json.loads(bridge.expose_latest_snapshot() or "")
    assert _apply_ops(first["root"], patch["ops"]) == latest["root"]
    assert patch.get("metadata") == latest.get("metadata")


def test_a_release_session_names_nodes_compactly_and_its_patches_apply() -> None:
    bridge = _counter_bridge(debug=False)
    first = json.loads(bridge.expose_envelope(-1))

    bridge.accept_action('{"intent":"increment","payload":{"by":2}}')
    patch = json.loads(bridge.expose_envelope(first["serial"]))

    assert [len(child["id"]) for child in first["root"]["children"]] == [1, 1]
    latest = json.loads(bridge.expose_latest_snapshot() or "")
    assert _apply_ops(first["root"], patch["ops"]) == latest["root"]


def test_an_unknown_base_or_another_session_gets_the_whole_snapshot() -> None:
    bridge = _counter_bridge()
    first = json.loads(bridge.expose_envelope(-1))
    assert (
        json.loads(bridge.expose_envelope(first["serial"] + 10_000))["kind"] == "full"
    )

    other = json.loads(_counter_bridge().expose_envelope(-1))
    assert other["serial"] != first["serial"]


def test_a_report_is_echoed_with_its_sequence_number() -> None:
    bridge = _counter_bridge()

    bridge.accept_action('{"intent":"increment","payload":{"by":2},"seq":3}')

    latest = json.loads(bridge.expose_latest_snapshot() or "")
    assert latest["metadata"]["echoes"] == [{"seq": 3, "target": "increment"}]


def test_a_report_that_changes_nothing_is_still_echoed() -> None:
    bridge = _counter_bridge()
    bridge.accept_action('{"intent":"increment","payload":{"by":2}}')

    bridge.accept_action('{"intent":"increment","payload":{"by":2},"seq":4}')

    latest = json.loads(bridge.expose_latest_snapshot() or "")
    assert latest["metadata"]["echoes"] == [{"seq": 4, "target": "increment"}]


def test_a_report_whose_handler_fails_is_still_echoed() -> None:
    actions = Actions()

    def fail(_state: State, _payload: object) -> State:
        raise RuntimeError("refused")

    actions.register("increment", fail)
    bridge = BridgeSurface(
        Store(State(root=Node(id="screen", type="Column", props=Props({})))), actions
    )

    bridge.accept_action('{"intent":"increment","payload":{"by":1},"seq":1}')

    latest = json.loads(bridge.expose_latest_snapshot() or "")
    assert latest["metadata"]["echoes"] == [{"seq": 1, "target": "increment"}]
    assert "refused" in bridge.expose_latest_error()


@pytest.mark.parametrize("seq", ["0", "-1", "1.5", "true", '"1"'])
def test_a_malformed_sequence_number_is_refused(seq: str) -> None:
    bridge = _counter_bridge()

    bridge.accept_action(f'{{"intent":"increment","payload":{{"by":2}},"seq":{seq}}}')

    assert "seq" in bridge.expose_latest_error()


def test_every_envelope_names_its_surface() -> None:
    bridge = _counter_bridge()
    first = json.loads(bridge.expose_envelope(-1))
    bridge.accept_action('{"intent":"increment","payload":{"by":2}}')
    patch = json.loads(bridge.expose_envelope(first["serial"]))

    assert (first["surface"], patch["surface"]) == ("main", "main")


def test_a_pull_or_an_action_for_another_surface_is_refused() -> None:
    bridge = _counter_bridge()

    assert bridge.expose_envelope(-1, "dialog") == ""
    bridge.accept_action('{"intent":"increment","payload":{"by":2},"surface":"dialog"}')

    assert "unknown surface" in bridge.expose_latest_error()


def test_a_pass_over_budget_is_reported_in_debug(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pycompose.bridge import api

    monkeypatch.setattr(api, "PASS_BUDGET", 0.0)
    bridge = _counter_bridge()

    bridge.accept_action('{"intent":"increment","payload":{"by":2}}')

    assert "over the 0 ms budget" in caplog.text


def test_the_last_pass_reports_its_time_by_phase() -> None:
    store = Store(State(root=Node(id="title", type="Text", props=Props({"text": "0"}))))
    actions = Actions()

    def increment(state: State, payload: dict[str, int]) -> State:
        text = str(payload["by"])
        return replace(
            state, root=Node(id="title", type="Text", props=Props({"text": text}))
        )

    actions.register("increment", increment)
    bridge = BridgeSurface(store, actions)
    bridge.accept_action('{"intent":"increment","payload":{"by":1}}')
    phases = json.loads(bridge.expose_last_pass())
    # What the host's pass log splits its Python stage into.
    assert set(phases) == {"handler", "view", "validate", "serialize"}
    assert all(spent >= 0 for spent in phases.values())
