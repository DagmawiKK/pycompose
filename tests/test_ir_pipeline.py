"""Ownership and depth guarantees at the public IR pipeline seams."""

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pycompose.core import Node, Props
from pycompose.core.props import JsonValue
from pycompose.errors import IrError, IrValidationError
from pycompose.ir import IRRoot, emit_ir, to_dict, to_json, to_json_bytes, validate_ir
from pycompose.state import State
from pycompose.utils.json_canonical import canonical_json, check_json


def test_node_detaches_raw_mapping_props_at_construction() -> None:
    source = {"modifier": {"padding": [1, 2]}}
    node = Node(id="root", type="Spacer", props=source)
    source["modifier"]["padding"].append(3)
    assert isinstance(node.props, Props)
    assert node.props.to_wire() == {"modifier": {"padding": [1, 2]}}


def test_props_detach_ten_thousand_nested_containers_without_recursion() -> None:
    value: JsonValue = "leaf"
    for _ in range(10000):
        value = {"a": [value]}
    props = Props({"modifier": value})
    wire = props.to_wire()["modifier"]
    for _ in range(10000):
        assert isinstance(wire, dict)
        array = wire["a"]
        assert isinstance(array, list)
        wire = array[0]
    assert wire == "leaf"


def test_canonical_json_encodes_ten_thousand_levels_without_recursion() -> None:
    value: JsonValue = "leaf"
    for _ in range(10000):
        value = {"a": [value]}
    assert canonical_json(value) == '{"a":[' * 10000 + '"leaf"' + "]}" * 10000


JSON_SCALARS = (
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(alphabet=st.characters(blacklist_categories=("Cs",)))
)
JSON_VALUES = st.recursive(
    JSON_SCALARS,
    lambda child: st.lists(child, max_size=5)
    | st.dictionaries(
        st.text(alphabet=st.characters(blacklist_categories=("Cs",))), child, max_size=5
    ),
    max_leaves=30,
)


@given(JSON_VALUES)
def test_canonical_json_matches_standard_library_bytes(value: JsonValue) -> None:
    expected = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    assert canonical_json(value) == expected


def test_valid_snapshot_is_preserved_by_identity() -> None:
    snapshot = IRRoot(
        root=Node(id="root", type="Text", props=Props({"text": "hello"})),
        schema_version="1.0.0",
        metadata={"route": ["home"]},
    )
    result = validate_ir(snapshot)
    assert result.snapshot is snapshot
    assert result.issues == ()


def test_validation_preserves_two_thousand_level_snapshot_without_recursion() -> None:
    root = Node(id="leaf", type="Text", props=Props({"text": "hello"}))
    for index in range(2000):
        root = Node(id=f"node{index}", type="Column", children=(root,))
    snapshot = IRRoot(root=root, schema_version="1.0.0")
    assert validate_ir(snapshot).snapshot is snapshot


def test_emission_qualifies_two_thousand_levels_without_recursion() -> None:
    root = Node(id="leaf", type="Spacer")
    for _ in range(2000):
        root = Node(id="a", type="Column", children=(root,))
    snapshot = emit_ir(State(root=root), "1.0.0")
    assert snapshot.root.id == "root"
    leaf = snapshot.root
    for _ in range(2000):
        leaf = leaf.children[0]
    assert leaf.id == "root." + "a." * 1999 + "leaf"


def test_two_thousand_level_pipeline_serializes_without_recursion() -> None:
    root = Node(id="leaf", type="Spacer")
    for _ in range(2000):
        root = Node(id="a", type="Column", children=(root,))
    candidate = emit_ir(State(root=root), "1.0.0")
    result = validate_ir(candidate)
    assert result.snapshot is candidate
    wire = to_dict(candidate)["root"]
    for _ in range(2000):
        assert isinstance(wire, dict)
        children = wire["children"]
        assert isinstance(children, list)
        wire = children[0]
    assert isinstance(wire, dict)
    assert wire["type"] == "Spacer"
    encoded = to_json_bytes(candidate)
    assert encoded.count(b'"children":[') == 2000
    assert encoded.endswith(b'"schemaVersion":"1.0.0","version":"0.1.0"}')
    assert to_json(candidate).encode("utf-8") == encoded


def test_release_rebuilds_only_degraded_branches_and_keeps_frozen_props() -> None:
    keep = Node(id="keep", type="Text", props=Props({"text": "keep"}))
    original_props = Props(
        {"text": "fix", "style": "bad", "modifier": {"padding": [4]}}
    )
    fix = Node(id="fix", type="Text", props=original_props)
    branch = Node(id="branch", type="Column", children=(fix,))
    snapshot = IRRoot(
        root=Node(id="root", type="Column", children=(keep, branch)),
        schema_version="1.0.0",
        metadata={"route": "home"},
    )
    result = validate_ir(snapshot, debug=False)
    assert result.snapshot is not None
    assert result.snapshot.root is not snapshot.root
    assert result.snapshot.root.children[0] is keep
    changed = result.snapshot.root.children[1]
    assert changed is not branch
    assert changed.children[0].props["modifier"] is original_props["modifier"]
    assert result.snapshot.metadata is snapshot.metadata
    assert result.issues[0].path == ("root", "branch", "fix")
    assert "style" in fix.props


def test_shared_subtrees_are_not_cycles_and_get_unique_emitted_ids() -> None:
    shared = Node(id="item", type="Text", props=Props({"text": "shared"}))
    state = State(
        root=Node(
            id="root",
            type="Column",
            children=(
                Node(id="left", type="Column", children=(shared,)),
                Node(id="right", type="Column", children=(shared,)),
            ),
        )
    )
    candidate = emit_ir(state, "1.0.0")
    assert validate_ir(candidate).snapshot is candidate
    assert candidate.root.children[0].children[0].id == "root.left.item"
    assert candidate.root.children[1].children[0].id == "root.right.item"
    assert to_json_bytes(candidate).count(b'"text":"shared"') == 2


@pytest.mark.parametrize("component", ["Column", "Unknown", "Spacer"])
def test_cycles_reject_the_whole_candidate_even_inside_a_dropped_subtree(
    component: str,
) -> None:
    cyclic = Node(id="cycle", type=component)
    # Bypass frozen construction to exercise malformed input at public boundaries.
    object.__setattr__(cyclic, "children", (cyclic,))
    snapshot = IRRoot(
        root=Node(id="root", type="Column", children=(cyclic,)), schema_version="1.0.0"
    )
    with pytest.raises(IrValidationError):
        validate_ir(snapshot)
    result = validate_ir(snapshot, debug=False)
    assert result.snapshot is None
    assert result.issues[-1].message == "cyclic node graph"
    assert result.issues[-1].path == ("root", "cycle", "cycle")
    with pytest.raises(IrValidationError, match="cyclic"):
        emit_ir(State(root=snapshot.root), "1.0.0")
    with pytest.raises(IrValidationError, match="cyclic"):
        to_json_bytes(snapshot)
    with pytest.raises(IrValidationError, match="cyclic"):
        to_dict(snapshot)


def test_deep_props_and_metadata_validate_and_encode_without_recursion() -> None:
    nested: JsonValue = None
    for _ in range(10000):
        nested = {"a": [nested]}
    snapshot = IRRoot(
        root=Node(id="root", type="Spacer", props=Props({"modifier": nested})),
        schema_version="1.0.0",
        metadata={"nested": nested},
    )
    assert validate_ir(snapshot).snapshot is snapshot
    assert to_json_bytes(snapshot).count(b'{"a":[') == 20000


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", 123),
        ("type", []),
        ("props", []),
        ("children", ["not a node"]),
        ("children", None),
        ("children", 123),
    ],
)
def test_node_rejects_invalid_structural_field_types(field: str, value: object) -> None:
    kwargs = {"id": "root", "type": "Column", field: value}
    with pytest.raises(IrError):
        Node(**kwargs)  # type: ignore[arg-type]


@given(JSON_VALUES)
def test_standalone_serialization_remains_detached_and_byte_compatible(
    value: JsonValue,
) -> None:
    snapshot = IRRoot(
        root=Node(id="root", type="Spacer", props=Props({"modifier": value})),
        schema_version="1.0.0",
        metadata={"payload": value},
    )
    expected = json.dumps(
        to_dict(snapshot),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    assert to_json_bytes(snapshot) == expected
    wire = to_dict(snapshot)
    assert isinstance(wire["root"], dict)
    wire["root"]["props"] = {}
    assert to_json_bytes(snapshot) == expected


def test_integer_subclasses_use_base_integer_formatting_in_every_container() -> None:
    class Count(int):
        def __str__(self) -> str:
            return "not-json"

        def __repr__(self) -> str:
            return "also-not-json"

    count = Count(7)
    snapshot = IRRoot(
        root=Node(
            id="root",
            type="Spacer",
            props={"modifier": {"padding": count, "items": []}},
        ),
        schema_version="1.0.0",
        metadata={"count": count, "items": []},
    )
    assert validate_ir(snapshot).snapshot is snapshot
    expected = json.dumps(
        to_dict(snapshot), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    assert to_json_bytes(snapshot) == expected
    assert canonical_json(count) == "7"


def test_json_checker_and_writer_agree_that_ordinary_tuples_are_not_json() -> None:
    with pytest.raises(IrValidationError):
        check_json((1,))
    with pytest.raises(IrValidationError):
        canonical_json((1,))


def test_string_subclasses_cannot_hide_invalid_utf8_values_or_keys() -> None:
    class FakeText(str):
        def encode(self, *_args: object, **_kwargs: object) -> bytes:
            return b"looks-valid"

    bad = FakeText("\ud800")
    for value in (bad, {bad: []}):
        with pytest.raises(IrValidationError):
            check_json(value)
        snapshot = IRRoot(
            root=Node(id="root", type="Spacer", props={"modifier": {"value": value}}),
            schema_version="1.0.0",
        )
        with pytest.raises(IrValidationError, match="invalid prop value"):
            validate_ir(snapshot)
        result = validate_ir(snapshot, debug=False)
        assert result.snapshot is not None
        assert "modifier" not in result.snapshot.root.props
        assert b'"props":{}' in to_json_bytes(result.snapshot)
