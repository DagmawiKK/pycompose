"""Generated-table validation through the public snapshot API."""

from __future__ import annotations

import pytest

from pycompose.contract.catalog import REGISTRY
from pycompose.core import Node, Props
from pycompose.core.props import JsonValue
from pycompose.errors import IrValidationError, SchemaError
from pycompose.state import State
from pycompose.ui._rules import validate_modifier
from pycompose.wire import IRRoot, emit_ir, to_json_bytes, validate_ir


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


def test_duplicate_ids_fail_closed() -> None:
    leaf = Node(id="same", type="Text", props=Props({"text": "hello"}))
    snapshot = IRRoot(
        root=Node(id="root", type="Column", children=(leaf, leaf)),
        schema_version="1.0.0",
    )
    with pytest.raises(IrValidationError, match="duplicate node id"):
        validate_ir(snapshot)


def test_leaf_children_are_rejected() -> None:
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


@pytest.mark.parametrize(
    ("schema_version", "library_version"),
    [("0.9.9", "0.1.0"), ("1.0.0", "0.0.9"), ("9.9.9", "0.1.0"), ("bad", "0.1.0")],
)
def test_version_mismatch_is_never_silently_degraded(
    schema_version: str, library_version: str
) -> None:
    with pytest.raises(SchemaError):
        validate_ir(
            IRRoot(
                root=Node(id="root", type="Column"),
                schema_version=schema_version,
                version=library_version,
            )
        )


def test_invalid_metadata_is_rejected() -> None:
    snapshot = IRRoot(
        root=Node(id="root", type="Column"),
        schema_version="1.0.0",
        metadata={"bad": float("nan")},
    )
    with pytest.raises(IrValidationError, match="invalid metadata"):
        validate_ir(snapshot)


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


def test_invalid_identity_is_rejected_before_serialization() -> None:
    snapshot = IRRoot(root=Node(id="\ud800", type="Column"), schema_version="1.0.0")
    with pytest.raises(IrValidationError, match="invalid node identity"):
        validate_ir(snapshot)


@pytest.mark.parametrize(
    "modifier",
    [{}, {"size": 4}, {"operations": [], "extra": 1}],
)
def test_a_modifier_is_exactly_its_operations(modifier: dict[str, object]) -> None:
    """Python writes only ``{"operations": [...]}``; any other shape is refused."""
    with pytest.raises(IrValidationError, match="exactly its operations"):
        validate_modifier(modifier)
