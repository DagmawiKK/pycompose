"""Host-owned worker calls through the pure-data bridge seam."""

import json
import logging
from collections.abc import Mapping
from dataclasses import replace
from threading import Thread

import pytest

from pycompose.bridge import BridgeSurface
from pycompose.bridge.types import IncrementPayload, SubmitPayload
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
    assert bridge.accept_action('{"actionId":"increment","payload":{"by":2}}') is None
    assert bridge.expose_latest_snapshot() == (
        '{"root":{"id":"root","props":{"text":"2"},"type":"Text"},'
        '"schemaVersion":"1.18.0","version":"0.1.0"}'
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
        '{"actionId":"increment","payload":{"by":3}}',
        '{"actionId":"increment"}',
        '{"actionId":"increment","payload":{"by":2}}',
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
        '{"actionId":"missing"}',
        '{"actionId":"increment","payload":null}',
        '{"actionId":"increment","payload":{"by":true}}',
        '{"actionId":"increment","payload":{"by":1.5}}',
        '{"actionId":"increment","payload":{"by":NaN}}',
        '{"actionId":"increment","payload":{"extra":1}}',
        '{"actionId":"submit","payload":{}}',
        '{"actionId":"increment","extra":1}',
        '{"actionId":"increment","actionId":"submit","payload":{"email":"a"}}',
        '{"actionId":"increment","payload":{"by":2,"by":3}}',
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
    bridge.accept_action('{"actionId":"increment"}')
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
    thread = Thread(target=bridge.accept_action, args=('{"actionId":"increment"}',))
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
    bridge.accept_action(json.dumps({"actionId": "increment", "payload": increment}))
    bridge.accept_action(json.dumps({"actionId": "submit", "payload": submit}))
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
    bridge.accept_action('{"actionId":"increment"}')
    assert store.value is original
    assert bridge.expose_latest_snapshot() is before
    assert "handler failed" in caplog.text
    actions.register(
        "increment",
        lambda state, _payload: replace(
            state, root=Node(id="value", type="Text", props={"text": "next"})
        ),
    )
    bridge.accept_action('{"actionId":"increment"}')
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
    bridge.accept_action('{"actionId":"increment"}')
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
        bridge.accept_action('{"actionId":"increment"}')
        return replace(
            state, root=Node(id="value", type="Text", props={"text": "done"})
        )

    actions.register("increment", handler)
    bridge = BridgeSurface(store, actions)
    bridge.accept_action('{"actionId":"increment"}')
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
    bridge.accept_action('{"actionId":"increment"}')
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
    bridge.accept_action('{"actionId":"increment"}')
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
