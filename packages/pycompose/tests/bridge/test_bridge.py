"""Host-owned worker calls through the pure-data bridge seam."""

import json
import logging
from collections.abc import Mapping
from dataclasses import replace
from threading import Thread

import pytest
from handlers import Handlers

from pycompose.bridge import BridgeSurface
from pycompose.bridge.types import IncrementPayload, SubmitPayload
from pycompose.errors import SchemaError
from pycompose.model.canonical import FrozenJsonValue
from pycompose.model.catalog.lock import SCHEMA_VERSION
from pycompose.model.nodes import Node, Props
from pycompose.model.snapshot import Snapshot, SnapshotStore


def test_action_handler_publishes_the_next_canonical_snapshot() -> None:
    store = SnapshotStore(
        Snapshot(root=Node(id="title", type="Text", props=Props({"text": "0"})))
    )
    actions = Handlers()

    def increment(state: Snapshot, payload: dict[str, int]) -> Snapshot:
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
        '{"root":{"id":"0","props":{"text":"2"},"type":"Text"},'
        '"schemaVersion":"' + SCHEMA_VERSION + '","version":"0.1.0"}'
    )
    assert store.value.root.props.values["text"] == "2"


def test_fifo_actions_apply_payload_defaults_and_preserve_order() -> None:
    store = SnapshotStore(
        Snapshot(root=Node(id="value", type="Text", props={"text": "start"}))
    )
    actions = Handlers()
    calls: list[object] = []

    def append(state: Snapshot, payload: Mapping[str, FrozenJsonValue]) -> Snapshot:
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
    store = SnapshotStore(
        Snapshot(root=Node(id="value", type="Text", props={"text": "unchanged"}))
    )
    actions = Handlers()
    calls: list[str] = []

    def handler(state: Snapshot, _payload: object) -> Snapshot:
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
    original = Snapshot(root=Node(id="value", type="Text", props={"text": "unchanged"}))
    store = SnapshotStore(original)
    actions = Handlers()
    actions.register("increment", lambda state, _payload: replace(state))
    bridge = BridgeSurface(store, actions)
    before = bridge.expose_latest_snapshot()
    bridge.accept_action('{"intent":"increment"}')
    assert store.value is original
    assert bridge.expose_latest_snapshot() is before


def test_actions_from_another_thread_are_not_dispatched(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = SnapshotStore(
        Snapshot(root=Node(id="value", type="Text", props={"text": "start"}))
    )
    calls: list[str] = []
    actions = Handlers()

    def handler(state: Snapshot, _payload: object) -> Snapshot:
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
    actions = Handlers()

    def handler(state: Snapshot, payload: object) -> Snapshot:
        seen.append(payload)
        return state

    actions.register("increment", handler)
    actions.register("submit", handler)
    bridge = BridgeSurface(
        SnapshotStore(
            Snapshot(root=Node(id="text", type="Text", props={"text": "hi"}))
        ),
        actions,
    )
    bridge.accept_action(json.dumps({"intent": "increment", "payload": increment}))
    bridge.accept_action(json.dumps({"intent": "submit", "payload": submit}))
    assert seen == [{"by": 1}, {"email": "ada@example.com"}]


@pytest.mark.parametrize("debug", [True, False])
def test_handler_failure_preserves_state_and_allows_the_next_action(
    debug: bool, caplog: pytest.LogCaptureFixture
) -> None:
    original = Snapshot(root=Node(id="value", type="Text", props={"text": "old"}))
    store = SnapshotStore(original)
    actions = Handlers()

    def fail(_state: Snapshot, _payload: object) -> Snapshot:
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


def test_release_leaves_the_check_to_the_hosts_parse() -> None:
    """Release publishes what it emitted; the host's typed parse refuses it."""
    store = SnapshotStore(
        Snapshot(root=Node(id="value", type="Text", props={"text": "old"}))
    )
    actions = Handlers()
    actions.register(
        "increment",
        lambda state, _payload: replace(state, root=Node(id="value", type="Missing")),
    )
    bridge = BridgeSurface(store, actions, debug=False)
    bridge.accept_action('{"intent":"increment"}')
    assert '"type":"Missing"' in (bridge.expose_latest_snapshot() or "")


@pytest.mark.parametrize("debug", [True])
def test_invalid_next_snapshot_never_commits_partial_state(debug: bool) -> None:
    original = Snapshot(root=Node(id="value", type="Text", props={"text": "old"}))
    store = SnapshotStore(original)
    actions = Handlers()
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
    actions = Handlers()
    calls: list[str] = []
    store = SnapshotStore(
        Snapshot(root=Node(id="value", type="Text", props={"text": "old"}))
    )

    def handler(state: Snapshot, _payload: object) -> Snapshot:
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
    actions = Handlers()
    seen: list[Mapping[str, FrozenJsonValue]] = []

    def handler(state: Snapshot, payload: Mapping[str, FrozenJsonValue]) -> Snapshot:
        seen.append(payload)
        with pytest.raises(TypeError):
            payload["by"] = 5  # type: ignore[index]
        return state

    actions.register("increment", handler)
    bridge = BridgeSurface(
        SnapshotStore(
            Snapshot(root=Node(id="value", type="Text", props={"text": "hi"}))
        ),
        actions,
    )
    bridge.accept_action('{"intent":"increment"}')
    assert seen == [{"by": 1}]


def test_deep_snapshot_transition_is_not_limited_by_state_equality() -> None:
    def nested(text: str) -> Node:
        node = Node(id="leaf", type="Text", props={"text": text})
        for _ in range(1200):
            node = Node(id="child", type="Column", children=(node,))
        return node

    store = SnapshotStore(Snapshot(root=nested("old")))
    actions = Handlers()
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
            SnapshotStore(
                Snapshot(root=Node(id="text", type="Text", props={"text": "hi"}))
            ),
            Handlers(),
            schema_version="2.0.0",
            debug=debug,
        )


@pytest.mark.parametrize("debug", [True])
def test_invalid_initial_snapshot_is_unavailable_and_logged_in_debug(
    debug: bool, caplog: pytest.LogCaptureFixture
) -> None:
    bridge = BridgeSurface(
        SnapshotStore(Snapshot(root=Node(id="text", type="Missing"))),
        Handlers(),
        debug=debug,
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

    actions = Handlers()
    actions.register(
        "increment",
        lambda state, payload: replace(state, root=screen(str(payload["by"]))),
    )
    return BridgeSurface(
        SnapshotStore(Snapshot(root=screen("0"))), actions, debug=debug
    )


def test_a_pull_from_a_known_base_is_a_patch_that_rebuilds_the_latest() -> None:
    bridge = _counter_bridge()
    first = json.loads(bridge.expose_envelope(-1))
    assert first["kind"] == "full"

    bridge.accept_action('{"intent":"increment","payload":{"by":2}}')
    patch = json.loads(bridge.expose_envelope(first["serial"]))

    assert (patch["kind"], patch["baseSerial"]) == ("patch", first["serial"])
    paths = bridge.node_paths()
    assert [(op["op"], paths[op["id"]]) for op in patch["ops"]] == [
        ("setProp", "root.count")
    ]
    latest = json.loads(bridge.expose_latest_snapshot() or "")
    assert _apply_ops(first["root"], patch["ops"]) == latest["root"]
    assert patch.get("metadata") == latest.get("metadata")


def test_debug_and_release_publish_the_same_bytes() -> None:
    """Debug differs only in what it keeps aside: the readable path table."""
    debug, release = _counter_bridge(debug=True), _counter_bridge(debug=False)
    published: list[tuple[str, str]] = []
    bases = {"debug": -1, "release": -1}
    for by in (2, 3, 3, 5):
        envelopes = []
        for name, bridge in (("debug", debug), ("release", release)):
            bridge.accept_action(
                json.dumps({"intent": "increment", "payload": {"by": by}})
            )
            envelope = json.loads(bridge.expose_envelope(bases[name]))
            bases[name] = envelope.pop("serial")
            envelope.pop("baseSerial", None)
            envelopes.append(json.dumps(envelope, sort_keys=True))
        published.append((debug.expose_latest_snapshot() or "", envelopes[0]))
        assert debug.expose_latest_snapshot() == release.expose_latest_snapshot()
        assert envelopes[0] == envelopes[1]
    assert [
        len(child["id"]) for child in json.loads(published[0][0])["root"]["children"]
    ] == [1, 1]
    assert release.node_paths() == {}
    assert set(debug.node_paths().values()) >= {"root", "root.title", "root.count"}


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
    actions = Handlers()

    def fail(_state: Snapshot, _payload: object) -> Snapshot:
        raise RuntimeError("refused")

    actions.register("increment", fail)
    bridge = BridgeSurface(
        SnapshotStore(Snapshot(root=Node(id="screen", type="Column", props=Props({})))),
        actions,
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
    store = SnapshotStore(
        Snapshot(root=Node(id="title", type="Text", props=Props({"text": "0"})))
    )
    actions = Handlers()

    def increment(state: Snapshot, payload: dict[str, int]) -> Snapshot:
        text = str(payload["by"])
        return replace(
            state, root=Node(id="title", type="Text", props=Props({"text": text}))
        )

    actions.register("increment", increment)
    bridge = BridgeSurface(store, actions)
    json.loads(bridge.expose_last_pass())  # forget the first snapshot's
    bridge.accept_action('{"intent":"increment","payload":{"by":1}}')
    bridge.accept_action('{"intent":"increment","payload":{"by":2}}')
    bridge.expose_envelope(-1)
    phases = json.loads(bridge.expose_last_pass())
    # What the host's pass log splits Python's work into: every action the
    # host ran, then the one snapshot drawn for all of them when it pulled.
    assert set(phases) == {
        "handler",
        "compose",
        "view",
        "validate",
        "serialize",
        "accept",
        "actions",
    }
    assert phases["actions"] == 2
    assert phases["accept"] >= phases["handler"]
    assert json.loads(bridge.expose_last_pass()) == {}


def test_actions_before_a_pull_are_drawn_once() -> None:
    """A text field reports its text and its caret; the host pulls once."""
    store = SnapshotStore(
        Snapshot(root=Node(id="title", type="Text", props=Props({"text": "0"})))
    )
    actions = Handlers()
    actions.register(
        "increment",
        lambda state, payload: replace(
            state,
            root=Node(
                id="title", type="Text", props=Props({"text": str(payload["by"])})
            ),
        ),
    )
    bridge = BridgeSurface(store, actions)
    published = bridge.counters()["published"]
    bridge.accept_action('{"intent":"increment","payload":{"by":1}}')
    bridge.accept_action('{"intent":"increment","payload":{"by":2}}')
    assert bridge.counters()["published"] == published
    assert json.loads(bridge.expose_envelope(-1))["root"]["props"]["text"] == "2"
    assert bridge.counters()["published"] == published + 1
