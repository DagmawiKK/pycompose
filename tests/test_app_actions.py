"""App-defined actions through composition, canonical IR and worker dispatch."""

import json
from dataclasses import replace
from typing import Literal, TypedDict

import pytest

from pycompose import action
from pycompose.bridge import BridgeSurface
from pycompose.errors import IrValidationError
from pycompose.ir import emit_ir, to_json, validate_ir
from pycompose.m3 import FilledButton, FilterChip
from pycompose.state import Actions, State, Store


class RenamePayload(TypedDict):
    task_id: int
    value: str


class FilterPayload(TypedDict):
    value: Literal["all", "active", "done"]


@action
def rename(state: State, payload: RenamePayload) -> State:
    return replace(state, version=state.version + payload["task_id"])


@action
def choose_filter(state: State, payload: FilterPayload) -> State:
    return replace(state, version=len(payload["value"]))


def test_bound_app_action_round_trips_without_native_catalog_registration() -> None:
    binding = rename.bind(id="task_7", task_id=7)
    state = State(root=FilledButton(id="rename", text="Rename", on_click=binding))
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
    binding = rename.bind(id="task_7", task_id=7)
    state = State(root=FilledButton(id="rename", text="Rename", on_click=binding))
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
    binding = choose_filter.bind(id="done", value="done")
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
        choose_filter.bind(id="bad", value="archived")
