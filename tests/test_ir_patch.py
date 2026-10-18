"""ir.patch: value diffing into byte-stable pull envelopes."""

from __future__ import annotations

import json

from hypothesis import given
from hypothesis import strategies as st

from pycompose.core import ROOT_ID, Node, Props, child_id
from pycompose.ir.model import IRRoot
from pycompose.ir.patch import (
    PatchOp,
    ReplaceSubtree,
    SetProp,
    diff_nodes,
    full_bytes,
    patch_bytes,
)
from pycompose.ir.serializer import to_json_bytes
from pycompose.utils.json_canonical import canonical_json_bytes

SCHEMA_VERSION = "1.0.0"


def _snapshot(root: Node, metadata: dict[str, object] | None = None) -> IRRoot:
    return IRRoot(root=root, schema_version=SCHEMA_VERSION, metadata=metadata)


def _text(text: str, *, slot: str | None = None) -> Node:
    return Node(id=ROOT_ID, type="Text", props=Props({"text": text}), slot=slot)


# --- diff cases ------------------------------------------------------------


def test_diff_prop_change_is_a_single_set_prop() -> None:
    ops = diff_nodes(_text("hi"), _text("hi!"))
    assert ops == (SetProp(id=ROOT_ID, prop="text", value="hi!"),)


def test_diff_added_prop_is_a_set_prop() -> None:
    base = Node(id=ROOT_ID, type="Text", props=Props({}))
    assert diff_nodes(base, _text("a")) == (
        SetProp(id=ROOT_ID, prop="text", value="a"),
    )


def test_diff_removed_prop_ships_the_node_whole() -> None:
    new = Node(id=ROOT_ID, type="Text", props=Props({}))
    assert diff_nodes(_text("a"), new) == (ReplaceSubtree(id=ROOT_ID, payload=new),)


def test_diff_type_change_ships_the_node_whole() -> None:
    new = Node(id=ROOT_ID, type="Button", props=Props({"text": "a"}))
    assert diff_nodes(_text("a"), new) == (ReplaceSubtree(id=ROOT_ID, payload=new),)


def test_diff_root_id_change_ships_the_node_whole() -> None:
    new = Node(id="replaced", type="Text", props=Props({"text": "a"}))
    assert diff_nodes(_text("a"), new) == (ReplaceSubtree(id="replaced", payload=new),)


def test_diff_slot_change_ships_the_node_whole() -> None:
    new = _text("a", slot="bottomBar")
    assert diff_nodes(_text("a"), new) == (ReplaceSubtree(id=ROOT_ID, payload=new),)


def test_diff_child_count_change_ships_the_parent_whole() -> None:
    child = Node(id=child_id(ROOT_ID, 0), type="Text", props=Props({"text": "a"}))
    base = Node(id=ROOT_ID, type="Column", children=(child,))
    new = Node(id=ROOT_ID, type="Column", children=(child, child))
    assert diff_nodes(base, new) == (ReplaceSubtree(id=ROOT_ID, payload=new),)


def test_diff_child_id_change_ships_the_parent_whole() -> None:
    base_child = Node(id="root.a", type="Text", props=Props({"text": "a"}))
    new_child = Node(id="root.b", type="Text", props=Props({"text": "a"}))
    base = Node(id=ROOT_ID, type="Column", children=(base_child,))
    new = Node(id=ROOT_ID, type="Column", children=(new_child,))
    assert diff_nodes(base, new) == (ReplaceSubtree(id=ROOT_ID, payload=new),)


def test_diff_deep_prop_change_is_one_op() -> None:
    leaf_id = child_id(child_id(ROOT_ID, 0), 1)
    base = Node(
        id=ROOT_ID,
        type="Column",
        children=(
            Node(
                id=child_id(ROOT_ID, 0),
                type="Row",
                children=(Node(id=leaf_id, type="Text", props=Props({"text": "a"})),),
            ),
        ),
    )
    new = Node(
        id=ROOT_ID,
        type="Column",
        children=(
            Node(
                id=child_id(ROOT_ID, 0),
                type="Row",
                children=(Node(id=leaf_id, type="Text", props=Props({"text": "b"})),),
            ),
        ),
    )
    assert diff_nodes(base, new) == (SetProp(id=leaf_id, prop="text", value="b"),)


def test_diff_prefers_the_topmost_changed_subtree() -> None:
    leaf_id = child_id(child_id(ROOT_ID, 0), 0)
    base_leaf = Node(id=leaf_id, type="Text", props=Props({"text": "a"}))
    new_leaf = Node(id=leaf_id, type="Text", props=Props({"text": "b"}))
    base = Node(
        id=ROOT_ID,
        type="Column",
        children=(Node(id=child_id(ROOT_ID, 0), type="Row", children=(base_leaf,)),),
    )
    new = Node(
        id=ROOT_ID,
        type="Column",
        children=(Node(id=child_id(ROOT_ID, 0), type="Box", children=(new_leaf,)),),
    )
    assert diff_nodes(base, new) == (
        ReplaceSubtree(id=new.children[0].id, payload=new.children[0]),
    )


def test_diff_skips_shared_branches_by_identity() -> None:
    shared = Node(id="root.a", type="Text", props=Props({"text": "same"}))
    base = Node(
        id=ROOT_ID,
        type="Column",
        children=(shared, Node(id="root.b", type="Text", props=Props({"text": "a"}))),
    )
    new = Node(
        id=ROOT_ID,
        type="Column",
        children=(shared, Node(id="root.b", type="Text", props=Props({"text": "b"}))),
    )
    assert diff_nodes(base, new) == (SetProp(id="root.b", prop="text", value="b"),)


# --- envelope bytes --------------------------------------------------------


def test_full_envelope_is_the_snapshot_plus_kind_and_serial() -> None:
    root = _snapshot(_text("hi"), metadata={"data": {"note": "a"}})
    raw = full_bytes(root, serial=3)
    value = json.loads(raw)
    assert value["kind"] == "full"
    assert value["serial"] == 3
    assert value["schemaVersion"] == SCHEMA_VERSION
    assert value["metadata"] == {"data": {"note": "a"}}
    snapshot = json.loads(to_json_bytes(root))
    assert {
        key: value[key] for key in ("root", "schemaVersion", "version", "metadata")
    } == snapshot
    assert canonical_json_bytes(value) == raw


def test_patch_envelope_carries_serials_metadata_and_ops() -> None:
    root = _snapshot(_text("hi!"), metadata={"data": {"note": "a"}})
    ops = diff_nodes(_text("hi"), root.root)
    raw = patch_bytes(root, ops, base_serial=4, serial=5)
    value = json.loads(raw)
    assert value["kind"] == "patch"
    assert value["baseSerial"] == 4
    assert value["serial"] == 5
    assert value["schemaVersion"] == SCHEMA_VERSION
    assert value["metadata"] == {"data": {"note": "a"}}
    assert value["ops"] == [
        {"id": ROOT_ID, "op": "setProp", "prop": "text", "value": "hi!"}
    ]
    assert canonical_json_bytes(value) == raw


def test_patch_envelope_serializes_replace_ops_and_empty_op_lists() -> None:
    new = Node(id=ROOT_ID, type="Text", props=Props({}))
    root = _snapshot(new)
    ops = diff_nodes(_text("hi"), new)
    value = json.loads(patch_bytes(root, ops, base_serial=1, serial=2))
    assert value["ops"] == [
        {
            "id": ROOT_ID,
            "op": "replaceSubtree",
            "payload": {"id": ROOT_ID, "props": {}, "type": "Text"},
        }
    ]
    empty = json.loads(patch_bytes(root, (), base_serial=2, serial=2))
    assert empty["ops"] == []


def test_patch_bytes_omits_absent_metadata() -> None:
    value = json.loads(patch_bytes(_snapshot(_text("a")), (), base_serial=1, serial=1))
    assert "metadata" not in value


def test_envelopes_are_byte_stable_and_deterministic() -> None:
    root = _snapshot(_text("hi!"))
    ops = diff_nodes(_text("hi"), root.root)
    first = patch_bytes(root, ops, base_serial=1, serial=2)
    second = patch_bytes(root, ops, base_serial=1, serial=2)
    assert first == second
    assert full_bytes(root, serial=2) == full_bytes(root, serial=2)


def test_a_prop_patch_is_orders_of_magnitude_smaller_than_the_snapshot() -> None:
    leaves = tuple(
        Node(id=f"root.item{index}", type="Text", props=Props({"text": "note"}))
        for index in range(64)
    )
    edited = Node(id="root.item63", type="Text", props=Props({"text": "notes"}))
    base = Node(id=ROOT_ID, type="Column", children=leaves)
    new = Node(id=ROOT_ID, type="Column", children=(*leaves[:-1], edited))
    ops = diff_nodes(base, new)
    assert ops == (SetProp(id="root.item63", prop="text", value="notes"),)
    root = _snapshot(new)
    patch = patch_bytes(root, ops, base_serial=1, serial=2)
    full = full_bytes(root, serial=2)
    assert len(patch) < len(full) // 10


# --- property: apply(diff) rebuilds the published root ---------------------


def _child_on_path(parent: Node, node_id: str) -> int:
    for index, child in enumerate(parent.children):
        if node_id == child.id or node_id.startswith(child.id + "."):
            return index
    raise AssertionError(f"no child on the path to {node_id!r}")


def _rewrite_props(node: Node, op: SetProp) -> Node:
    if node.id == op.id:
        return Node(
            id=node.id,
            type=node.type,
            props=Props({**node.props.values, op.prop: op.value}),
            children=node.children,
            slot=node.slot,
        )
    index = _child_on_path(node, op.id)
    children = list(node.children)
    children[index] = _rewrite_props(children[index], op)
    return Node(
        id=node.id,
        type=node.type,
        props=node.props,
        children=tuple(children),
        slot=node.slot,
    )


def _rewrite_node(node: Node, node_id: str, payload: Node) -> Node:
    if node.id == node_id:
        return payload
    index = _child_on_path(node, node_id)
    children = list(node.children)
    children[index] = _rewrite_node(children[index], node_id, payload)
    return Node(
        id=node.id,
        type=node.type,
        props=node.props,
        children=tuple(children),
        slot=node.slot,
    )


def _apply(root: Node, ops: tuple[PatchOp, ...]) -> Node:
    for op in ops:
        if isinstance(op, SetProp):
            root = _rewrite_props(root, op)
        else:
            root = _rewrite_node(root, op.id, op.payload)
    return root


NAMES = st.sampled_from(("text", "label", "value", "enabled", "count"))
VALUES = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-4, max_value=4),
    st.text(alphabet="abé", max_size=3),
    st.lists(st.integers(min_value=0, max_value=3), max_size=2),
    st.dictionaries(
        st.sampled_from(("k", "m")), st.integers(min_value=0, max_value=3), max_size=2
    ),
)
TYPES = st.sampled_from(("Text", "Column", "Row", "Box"))
SLOTS = st.sampled_from((None, "topBar", "bottomBar"))
RAW_TREES = st.recursive(
    st.builds(
        Node,
        id=st.just("leaf"),
        type=TYPES,
        props=st.dictionaries(NAMES, VALUES, max_size=2),
        slot=SLOTS,
    ),
    lambda child: st.builds(
        Node,
        id=st.just("layout"),
        type=TYPES,
        props=st.dictionaries(NAMES, VALUES, max_size=2),
        slot=SLOTS,
        children=st.lists(child, max_size=3),
    ),
    max_leaves=8,
)


def _qualify(node: Node, node_id: str) -> Node:
    children = tuple(
        _qualify(child, f"{node_id}.{index}")
        for index, child in enumerate(node.children)
    )
    return Node(
        id=node_id,
        type=node.type,
        props=node.props,
        children=children,
        slot=node.slot,
    )


@given(base=RAW_TREES, new=RAW_TREES)
def test_diff_apply_rebuilds_the_published_root(base: Node, new: Node) -> None:
    base = _qualify(base, ROOT_ID)
    new = _qualify(new, ROOT_ID)
    assert _apply(base, diff_nodes(base, new)) == new


@given(base=RAW_TREES, new=RAW_TREES)
def test_diff_is_empty_exactly_when_the_trees_are_equal(base: Node, new: Node) -> None:
    base = _qualify(base, ROOT_ID)
    new = _qualify(new, ROOT_ID)
    assert (diff_nodes(base, new) == ()) == (base == new)
