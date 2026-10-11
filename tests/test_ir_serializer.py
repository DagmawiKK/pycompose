"""ir.serializer: canonical JSON serialization."""

from __future__ import annotations

from pycompose.core import ROOT_ID, Node, Props, child_id
from pycompose.ir import serializer


def test_serialize_simple_node_canonical_keys() -> None:
    root = Node(id=ROOT_ID, type="Text", props=Props({"text": "hi"}))
    data = serializer.to_dict(root)
    assert list(data.keys()) == ["children", "id", "props", "type"]


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
