"""Public IR emission: versioned, deterministic snapshots."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from pycompose_testing.helpers import read_golden
from readable import ids, readable

from pycompose.core import Node, Props
from pycompose.errors import IrError, IrValidationError, SchemaError
from pycompose.ir import emit_ir, to_json_bytes, validate_ir
from pycompose.state import State


def test_emit_ir_matches_golden_and_generated_schema() -> None:
    state = State(
        root=Node(
            id="root",
            type="Column",
            children=(
                Node(id="root.0", type="Text", props=Props({"text": "Hello"})),
                Node(
                    id="root.1",
                    type="Button",
                    props=Props({"text": "Add", "onClick": "increment"}),
                ),
            ),
        ),
        version=7,
    )
    snapshot = emit_ir(state, "1.0.0")
    expected = read_golden("ir_counter.json")
    assert to_json_bytes(snapshot) == expected
    assert to_json_bytes(emit_ir(state, "1.0.0")) == expected
    schema_path = Path(__file__).parents[1] / "schema" / "ir.schema.json"
    jsonschema.validate(json.loads(expected), json.loads(schema_path.read_text()))


@pytest.mark.parametrize("version", ["0.9.9", "2.0.0", "1.0", "1.0.0-dev", "01.0.0"])
def test_emitter_rejects_old_unsupported_and_malformed_schema_versions(
    version: str,
) -> None:
    with pytest.raises(SchemaError):
        emit_ir(State(root=Node(id="root", type="Column")), version)


def test_emitter_qualifies_stable_keys_and_preserves_action_ids() -> None:
    state = State(
        root=Node(
            id="screen",
            type="Column",
            children=(
                Node(id="label", type="Text", props=Props({"text": "hi"})),
                Node(
                    id="submit",
                    type="Button",
                    props=Props({"text": "Go", "onClick": "submit"}),
                ),
            ),
        )
    )
    snapshot = emit_ir(state, "1.0.0")
    named = readable(state, "1.0.0")["root"]
    assert named["id"] == "root"
    assert [child["id"] for child in named["children"]] == [
        "root.label",
        "root.submit",
    ]
    assert snapshot.root.children[1].props["onClick"] == "submit"
    assert state.root.id == "screen"


def test_emitter_rejects_colliding_keys_and_invalid_props() -> None:
    child = Node(id="item", type="Text", props=Props({"text": "hi"}))
    with pytest.raises(IrError, match="duplicate node id"):
        emit_ir(
            State(root=Node(id="root", type="Column", children=(child, child))), "1.0.0"
        )
    with pytest.raises(IrValidationError, match="missing required prop"):
        validate_ir(emit_ir(State(root=Node(id="root", type="Text")), "1.0.0"))


def test_emission_detaches_nested_props_from_input_state() -> None:
    modifier = {"padding": [1, 2]}
    state = State(
        root=Node(id="root", type="Spacer", props=Props({"modifier": modifier}))
    )
    snapshot = emit_ir(state, "1.0.0")
    before = to_json_bytes(snapshot)
    modifier["padding"].append(3)
    assert to_json_bytes(snapshot) == before


def test_keyed_list_ids_survive_reordering() -> None:
    first = Node(id="first", type="Text", props=Props({"text": "one"}))
    second = Node(id="second", type="Text", props=Props({"text": "two"}))
    root = Node(id="root", type="LazyColumn", children=(first, second))
    reordered = Node(id="root", type="LazyColumn", children=(second, first))
    assert ids(readable(State(root=root), "1.0.0")["root"])[1:] == [
        "root.first",
        "root.second",
    ]
    assert ids(readable(State(root=reordered), "1.0.0")["root"])[1:] == [
        "root.second",
        "root.first",
    ]
