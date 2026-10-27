"""Generated-table validation through the public snapshot API."""

from __future__ import annotations

import pytest

from pycompose.contract.catalog import REGISTRY
from pycompose.core import Node, Props
from pycompose.core.props import JsonValue
from pycompose.errors import IrValidationError, SchemaError
from pycompose.ir import IRRoot, emit_ir, to_json_bytes, validate_ir
from pycompose.state import State


@pytest.mark.parametrize(
    ("node", "message"),
    [
        (Node(id="root", type="Unknown"), "unknown component"),
        (
            Node(id="root", type="Text", props=Props({"text": "hi", "extra": 1})),
            "unknown prop",
        ),
    ],
)
def test_debug_validation_rejects_unknown_types_and_props_with_context(
    node: Node, message: str
) -> None:
    with pytest.raises(IrValidationError, match=message) as excinfo:
        validate_ir(IRRoot(root=node, schema_version="1.0.0"))
    assert excinfo.value.context["node_id"] == "root"
    assert excinfo.value.context["node_type"] == node.type
    assert excinfo.value.context["path"] == ("root",)


def test_release_validation_drops_unknown_subtrees_and_ignores_extra_props() -> None:
    original = IRRoot(
        schema_version="1.0.0",
        root=Node(
            id="root",
            type="Column",
            children=(
                Node(
                    id="root.0",
                    type="Unknown",
                    children=(Node(id="root.0.0", type="Text"),),
                ),
                Node(id="root.1", type="Text", props=Props({"text": "hi", "extra": 1})),
            ),
        ),
    )
    result = validate_ir(original, debug=False)
    assert result.snapshot is not None
    assert result.snapshot.root.children == (
        Node(id="root.1", type="Text", props=Props({"text": "hi"})),
    )
    assert [issue.message for issue in result.issues] == [
        "unknown component",
        "unknown prop",
    ]
    assert original.root.children[1].props.get("extra") == 1
    assert validate_ir(original, debug=False) == result


def test_release_unknown_root_produces_no_snapshot() -> None:
    result = validate_ir(
        IRRoot(root=Node(id="root", type="Unknown"), schema_version="1.0.0"),
        debug=False,
    )
    assert result.snapshot is None
    assert result.issues[0].node_id == "root"


@pytest.mark.parametrize(
    ("component", "props", "message"),
    [
        ("Text", {}, "missing required prop"),
        ("Text", {"text": 1}, "invalid prop value"),
        ("Text", {"text": "hi", "style": "unknown"}, "invalid prop value"),
        ("Text", {"text": "hi", "color": 123}, "invalid prop value"),
        ("Spacer", {"modifier": []}, "invalid prop value"),
        ("Spacer", {"modifier": {"size": float("nan")}}, "invalid prop value"),
        ("Button", {"text": "Go", "onClick": "missing"}, "invalid prop value"),
        (
            "Button",
            {"text": "Go", "onClick": "submit", "enabled": 1},
            "invalid prop value",
        ),
    ],
)
def test_debug_validation_enforces_registry_prop_rules(
    component: str, props: dict[str, JsonValue], message: str
) -> None:
    with pytest.raises(IrValidationError, match=message):
        validate_ir(
            IRRoot(
                root=Node(id="root", type=component, props=Props(props)),
                schema_version="1.0.0",
            )
        )


def test_release_invalid_required_prop_drops_node_but_optional_prop_is_ignored() -> (
    None
):
    snapshot = IRRoot(
        schema_version="1.0.0",
        root=Node(
            id="root",
            type="Column",
            children=(
                Node(id="bad", type="Text", props=Props({"text": 1})),
                Node(
                    id="good",
                    type="Text",
                    props=Props({"text": "hi", "style": "wrong"}),
                ),
            ),
        ),
    )
    result = validate_ir(snapshot, debug=False)
    assert result.snapshot is not None
    assert result.snapshot.root.children == (
        Node(id="good", type="Text", props=Props({"text": "hi"})),
    )
    assert len(result.issues) == 2


def test_duplicate_ids_fail_closed_and_drop_later_node_in_release() -> None:
    leaf = Node(id="same", type="Text", props=Props({"text": "hello"}))
    snapshot = IRRoot(
        root=Node(id="root", type="Column", children=(leaf, leaf)),
        schema_version="1.0.0",
    )
    with pytest.raises(IrValidationError, match="duplicate node id"):
        validate_ir(snapshot)
    result = validate_ir(snapshot, debug=False)
    assert result.snapshot is not None
    assert result.snapshot.root.children == (leaf,)
    assert result.issues[0].node_id == "same"


def test_leaf_children_are_rejected_or_removed_in_release() -> None:
    snapshot = IRRoot(
        root=Node(
            id="root",
            type="Text",
            props=Props({"text": "hello"}),
            children=(Node(id="nested", type="Spacer"),),
        ),
        schema_version="1.0.0",
    )
    with pytest.raises(IrValidationError, match="children are not allowed"):
        validate_ir(snapshot)
    result = validate_ir(snapshot, debug=False)
    assert result.snapshot is not None
    assert result.snapshot.root.children == ()
    assert len(result.issues) == 1


@pytest.mark.parametrize("debug", [True, False])
@pytest.mark.parametrize(
    ("schema_version", "library_version"),
    [("0.9.9", "0.1.0"), ("1.0.0", "0.0.9"), ("9.9.9", "0.1.0"), ("bad", "0.1.0")],
)
def test_version_mismatch_is_never_silently_degraded(
    debug: bool, schema_version: str, library_version: str
) -> None:
    with pytest.raises(SchemaError):
        validate_ir(
            IRRoot(
                root=Node(id="root", type="Column"),
                schema_version=schema_version,
                version=library_version,
            ),
            debug=debug,
        )


def test_invalid_metadata_is_rejected_or_removed_with_a_release_diagnostic() -> None:
    snapshot = IRRoot(
        root=Node(id="root", type="Column"),
        schema_version="1.0.0",
        metadata={"bad": float("nan")},
    )
    with pytest.raises(IrValidationError, match="invalid metadata"):
        validate_ir(snapshot)
    result = validate_ir(snapshot, debug=False)
    assert result.snapshot is not None
    assert result.snapshot.metadata is None
    assert result.issues[0].message == "invalid metadata"


def test_emitted_snapshot_and_tables_cannot_be_mutated() -> None:
    snapshot = emit_ir(
        State(
            root=Node(
                id="root", type="Spacer", props=Props({"modifier": {"padding": [1, 2]}})
            )
        ),
        "1.0.0",
    )
    before = to_json_bytes(snapshot)
    modifier = snapshot.root.props["modifier"]
    with pytest.raises(TypeError):
        modifier["padding"] = []  # type: ignore[index]
    with pytest.raises(TypeError):
        modifier["padding"][0] = 3  # type: ignore[index]
    with pytest.raises(TypeError):
        REGISTRY.components["Text"].props["text"] = REGISTRY.components["Text"].props[
            "style"
        ]  # type: ignore[index]
    with pytest.raises(TypeError):
        REGISTRY.components["Text"] = REGISTRY.components["Column"]  # type: ignore[index]
    assert to_json_bytes(snapshot) == before


def test_metadata_is_frozen_but_serializes_as_plain_json() -> None:
    snapshot = IRRoot(
        root=Node(id="root", type="Column"),
        schema_version="1.0.0",
        metadata={"route": {"parts": ["home"]}},
    )
    with pytest.raises(TypeError):
        snapshot.metadata["route"]["parts"] = []  # type: ignore[index]
    assert b'"metadata":{"route":{"parts":["home"]}}' in to_json_bytes(snapshot)


def test_release_pipeline_can_degrade_emitted_unknown_nodes() -> None:
    state = State(
        root=Node(
            id="root",
            type="Column",
            children=(
                Node(id="unknown", type="Unknown"),
                Node(id="text", type="Text", props=Props({"text": "hi"})),
            ),
        )
    )
    result = validate_ir(emit_ir(state, "1.0.0"), debug=False)
    assert result.snapshot is not None
    assert [node.id for node in result.snapshot.root.children] == ["root.text"]
    assert len(result.issues) == 1


def test_invalid_identity_is_rejected_or_dropped_before_serialization() -> None:
    snapshot = IRRoot(root=Node(id="\ud800", type="Column"), schema_version="1.0.0")
    with pytest.raises(IrValidationError, match="invalid node identity"):
        validate_ir(snapshot)
    result = validate_ir(snapshot, debug=False)
    assert result.snapshot is None
    assert result.issues[0].message == "invalid node identity"
