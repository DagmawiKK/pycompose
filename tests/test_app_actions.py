"""App-defined actions through composition, canonical IR and worker dispatch."""

import json
from dataclasses import replace
from typing import Literal

import pytest

from pycompose import action
from pycompose.bridge import BridgeSurface
from pycompose.errors import IrValidationError
from pycompose.ir import emit_ir, to_json, validate_ir
from pycompose.m3 import Button, FilterChip
from pycompose.state import Actions, State, Store


@action
def rename(state: State, task_id: int, value: str) -> State:  # noqa: ARG001
    return replace(state, version=state.version + task_id)


@action
def choose_filter(state: State, value: Literal["all", "active", "done"]) -> State:
    return replace(state, version=len(value))


def test_bound_app_action_round_trips_without_native_catalog_registration() -> None:
    binding = rename.with_args(task_id=7)
    state = State(root=Button(id="rename", text="Rename", on_click=binding))
    snapshot = emit_ir(state, "1.2.0")
    assert validate_ir(snapshot).snapshot is snapshot
    metadata = json.loads(to_json(snapshot))["metadata"]["actionBindings"]
    assert metadata[str(binding)]["bound"] == {"taskId": 7}
    assert metadata[str(binding)]["payload"]["value"]["type"] == "string"
    store = Store(state)
    bridge = BridgeSurface(store, Actions(rename))
    bridge.accept_action(
        json.dumps({"actionId": str(binding), "payload": {"value": "New"}})
    )
    assert store.value.version == 7
    before = bridge.expose_latest_snapshot()
    bridge.accept_action(
        json.dumps({"actionId": str(binding), "payload": {"value": 3}})
    )
    assert bridge.expose_latest_snapshot() == before
    assert store.value.version == 7


def test_bound_values_cannot_be_overridden_and_old_envelopes_reject_app_bindings() -> (
    None
):
    binding = rename.with_args(task_id=7)
    state = State(root=Button(id="rename", text="Rename", on_click=binding))
    with pytest.raises(IrValidationError, match="schema"):
        validate_ir(emit_ir(state, "1.1.0"))
    store = Store(state)
    bridge = BridgeSurface(store, Actions(rename))
    bridge.accept_action(
        json.dumps(
            {"actionId": str(binding), "payload": {"value": "New", "taskId": 99}}
        )
    )
    assert store.value is state


def test_literal_payloads_survive_the_round_trip_through_frozen_metadata() -> None:
    binding = choose_filter.with_args(value="done")
    state = State(
        root=FilterChip(id="done", label="Done", selected=True, on_click=binding)
    )
    snapshot = emit_ir(state, "1.3.0")
    assert validate_ir(snapshot).snapshot is snapshot
    payload = json.loads(to_json(snapshot))["metadata"]["actionBindings"][str(binding)][
        "payload"
    ]
    assert payload["value"] == {
        "required": True,
        "type": "enum",
        "values": ["all", "active", "done"],
    }
    store = Store(state)
    bridge = BridgeSurface(store, Actions(choose_filter))
    bridge.accept_action(json.dumps({"actionId": str(binding), "payload": {}}))
    assert store.value.version == len("done")
    before = bridge.expose_latest_snapshot()
    bridge.accept_action(
        json.dumps({"actionId": str(binding), "payload": {"value": "archived"}})
    )
    assert bridge.expose_latest_snapshot() == before
    assert store.value.version == len("done")
    with pytest.raises(IrValidationError):
        choose_filter.with_args(value="archived")


@action
def pick(state: State, task_id: int) -> State:
    return replace(state, version=task_id)


@action
def advance(state: State) -> State:
    task = state.version + 1
    return replace(state, root=_primary(task), version=task)


def _primary(task: int) -> Button:
    return Button(
        id="primary",
        text=f"Task {task}",
        on_click=pick.with_args(task_id=task),
    )


def _serial(bridge: BridgeSurface) -> int:
    return int(json.loads(bridge.expose_envelope(-1))["serial"])


def test_a_tap_resolves_against_the_snapshot_the_user_saw() -> None:
    store = Store(State(root=_primary(10), version=10))
    bridge = BridgeSurface(store, Actions(pick, advance))
    binding = str(pick.with_args(task_id=10))
    seen = _serial(bridge)
    bridge.accept_action(json.dumps({"actionId": advance.name, "payload": {}}))

    bridge.accept_action(
        json.dumps({"actionId": binding, "payload": {}, "serial": seen})
    )

    assert store.value.version == 10


def test_a_tap_from_a_snapshot_no_longer_held_is_refused() -> None:
    store = Store(State(root=_primary(10), version=10))
    bridge = BridgeSurface(store, Actions(pick, advance))
    binding = str(pick.with_args(task_id=10))
    seen = _serial(bridge)
    for _ in range(9):
        bridge.accept_action(json.dumps({"actionId": advance.name, "payload": {}}))
    version = store.value.version

    bridge.accept_action(
        json.dumps({"actionId": binding, "payload": {}, "serial": seen})
    )

    assert store.value.version == version
    assert "stale action" in bridge.expose_latest_error()
