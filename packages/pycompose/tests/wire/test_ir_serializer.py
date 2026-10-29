"""ir.serializer: canonical JSON serialization."""

from __future__ import annotations

import json

import pytest

from pycompose.core import ROOT_ID, Node, Props, child_id
from pycompose.errors import IrValidationError
from pycompose.utils.json_canonical import canonical_json
from pycompose.wire import serializer


def test_serialize_simple_node_canonical_keys() -> None:
    root = Node(id=ROOT_ID, type="Text", props=Props({"text": "hi"}))
    data = serializer.to_dict(root)
    assert list(data.keys()) == ["id", "props", "type"]


def test_serialize_to_json_bytes_deterministic() -> None:
    child = Node(id=child_id(ROOT_ID, 0), type="Text", props=Props({"text": "a"}))
    root = Node(id=ROOT_ID, type="Column", children=(child,))
    b1 = serializer.to_json_bytes(root)
    b2 = serializer.to_json_bytes(root)
    assert b1 == b2
    assert isinstance(b1, bytes)


def test_serialize_to_json_string() -> None:
    root = Node(id=ROOT_ID, type="Text", props=Props({"text": "hi"}))
    s = serializer.to_json(root)
    assert "hi" in s


def test_canonical_json_round_trip_sorts_nested_objects_and_preserves_unicode() -> None:
    data = {"z": {"b": 1.25, "a": "é"}, "a": [True, None, -0.0]}
    expected = '{"a":[true,null,-0.0],"z":{"a":"é","b":1.25}}'
    assert canonical_json(data) == expected
    assert canonical_json(json.loads(expected)) == expected


@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
def test_serializer_rejects_non_finite_numbers_even_in_nested_modifiers(
    number: float,
) -> None:
    node = Node(id="root", type="Spacer", props=Props({"modifier": {"size": number}}))
    with pytest.raises(IrValidationError):
        serializer.to_json_bytes(node)


@pytest.mark.parametrize(
    "value", [{1: "coerced key"}, {"bad": object()}, {"bad": "\ud800"}, (1, 2)]
)
def test_canonical_writer_rejects_non_json_values(value: object) -> None:
    with pytest.raises(IrValidationError):
        canonical_json(value)


def test_canonical_writer_rejects_cycles() -> None:
    value: list[object] = []
    value.append(value)
    with pytest.raises(IrValidationError):
        canonical_json(value)


def test_props_reject_cyclic_json_with_a_domain_error() -> None:
    cycle: list[object] = []
    cycle.append(cycle)
    with pytest.raises(IrValidationError):
        Props({"modifier": {"cycle": cycle}})  # type: ignore[dict-item]
