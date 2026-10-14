"""Byte-stable packaged fixtures and schema coverage at the Python seam."""

import json
from pathlib import Path

import jsonschema
import pytest
from hypothesis import given
from hypothesis import strategies as st

from pycompose.components import (
    Box,
    Button,
    Column,
    LazyColumn,
    Modifier,
    Row,
    Spacer,
    Text,
    TextField,
)
from pycompose.core import Node
from pycompose.ir import emit_ir, to_json_bytes, validate_ir
from pycompose.ir.generated_validators import REGISTRY
from pycompose.state import State
from pycompose.testing.helpers import component_screen, golden_names, read_golden
from pycompose.utils.json_canonical import canonical_json_bytes


def test_golden_screen_rebuilds_match_packaged_fixture_exactly() -> None:
    expected = read_golden("component_screen.json")
    for _ in range(2):
        snapshot = emit_ir(State(root=component_screen()), "1.0.0")
        assert validate_ir(snapshot).snapshot is snapshot
        assert to_json_bytes(snapshot) == expected


def test_every_packaged_golden_is_canonical_and_schema_valid() -> None:
    names = golden_names()
    assert names == ("component_screen.json", "ir_counter.json", "resource_screen.json")
    schema = json.loads(
        (Path(__file__).parents[1] / "schema" / "ir.schema.json").read_text()
    )
    jsonschema.Draft7Validator.check_schema(schema)
    for name in names:
        expected = read_golden(name)
        value = json.loads(expected)
        assert canonical_json_bytes(value) == expected
        jsonschema.validate(value, schema)


TEXT = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=30)
LEAVES = st.one_of(
    TEXT.map(lambda text: Text(id="leaf", text=text)),
    TEXT.map(lambda text: Button(id="leaf", text=text, on_click="increment")),
    TEXT.map(lambda text: TextField(id="leaf", value=text, on_value_change="submit")),
    st.integers(min_value=0, max_value=48).map(
        lambda dp: Spacer(id="leaf", modifier=Modifier().padding(dp))
    ),
)


def _layout(
    pair: tuple[type[Column] | type[Row] | type[Box] | type[LazyColumn], list[Node]],
) -> Node:
    component, children = pair
    keyed = tuple(
        Node(
            id=f"item{index}",
            type=child.type,
            props=child.props,
            children=child.children,
        )
        for index, child in enumerate(children)
    )
    return component(id="layout", children=keyed)


TREES = st.recursive(
    LEAVES,
    lambda child: st.tuples(
        st.sampled_from((Column, Row, Box, LazyColumn)), st.lists(child, max_size=4)
    ).map(_layout),
    max_leaves=20,
)


def _rebuild(node: Node) -> Node:
    return Node(
        id=node.id,
        type=node.type,
        props=node.props.to_wire(),
        children=tuple(_rebuild(child) for child in node.children),
    )


@given(TREES)
def test_golden_property_independent_rebuilds_are_deterministic(root: Node) -> None:
    first = emit_ir(State(root=root), "1.0.0")
    second = emit_ir(State(root=_rebuild(root)), "1.0.0")
    assert validate_ir(first).snapshot is first
    assert validate_ir(second).snapshot is second
    assert to_json_bytes(first) == to_json_bytes(second)
    assert root.id != "root"


@given(TREES)
def test_golden_property_ids_are_unique_and_props_are_registry_known(
    root: Node,
) -> None:
    snapshot = emit_ir(State(root=root), "1.0.0")
    pending = [snapshot.root]
    ids = []
    while pending:
        node = pending.pop()
        ids.append(node.id)
        assert set(node.props) <= REGISTRY.components[node.type].props.keys()
        pending.extend(node.children)
    assert len(ids) == len(set(ids))


@given(st.lists(TEXT, min_size=0, max_size=15))
def test_golden_property_lazy_identity_survives_reordering(texts: list[str]) -> None:
    items = tuple(Text(id=f"key{index}", text=text) for index, text in enumerate(texts))
    first = emit_ir(State(root=LazyColumn(id="list", items=items)), "1.0.0")
    second = emit_ir(
        State(root=LazyColumn(id="list", items=tuple(reversed(items)))), "1.0.0"
    )
    assert [item.id for item in first.root.children] == list(
        reversed([item.id for item in second.root.children])
    )


def test_golden_reader_rejects_nonfixture_paths() -> None:
    with pytest.raises(ValueError, match="unknown golden"):
        read_golden("../__init__.py")
