"""Canonical JSON serializer for IR nodes."""

from __future__ import annotations

import json
from typing import Any

from pycompose.core.node import Node, Props
from pycompose.core.props import JsonValue

__all__ = ["node_to_dict", "to_dict", "to_json", "to_json_bytes"]


def _props_to_dict(props: Props) -> dict[str, JsonValue]:
    return dict(props.values)


def _node_to_dict(node: Node) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": node.id,
        "type": node.type,
        "props": _props_to_dict(node.props),
        "children": [_node_to_dict(child) for child in node.children],
    }
    return result


def node_to_dict(node: Node) -> dict[str, Any]:
    d = _node_to_dict(node)
    return {
        "children": d["children"],
        "id": d["id"],
        "props": d["props"],
        "type": d["type"],
    }


def to_dict(node: Node) -> dict[str, Any]:
    return node_to_dict(node)


def to_json(node: Node) -> str:
    data = to_dict(node)
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def to_json_bytes(node: Node) -> bytes:
    return to_json(node).encode("utf-8")
