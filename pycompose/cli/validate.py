"""Strict wire validation plus the existing registry/version/identity gate."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from pycompose.cli.project import ProjectError, read_json
from pycompose.cli.wire_schema import WireSchema
from pycompose.core import Node
from pycompose.ir import IRRoot, validate_ir


def _node(root: dict[str, Any]) -> Node:
    pending = [(root, False)]
    built: dict[int, Node] = {}
    while pending:
        raw, ready = pending.pop()
        if set(raw) - {"id", "type", "props", "children", "slot"}:
            raise ProjectError("unknown node fields", node_id=raw["id"])
        children = raw.get("children", [])
        if not ready:
            pending.append((raw, True))
            pending.extend((child, False) for child in reversed(children))
        else:
            built[id(raw)] = Node(
                id=raw["id"],
                type=raw["type"],
                props=raw["props"],
                children=tuple(built.pop(id(child)) for child in children),
                slot=raw.get("slot"),
            )
    return built[id(root)]


def validate_file(path: Path, *, wire: bool = True) -> None:
    """Validate an IR file without importing app code or requiring Android.

    Args:
        path: JSON snapshot file, canonical or ordinarily formatted.
        wire: Also check the bundled wire schema. It describes the library's
            catalog only, so an app's own components are checked by the
            runtime registry alone, once registered.

    Raises:
        ProjectError: If the envelope or metadata shape is invalid.
    """
    raw = read_json(path)
    if wire:
        WireSchema().check(raw)
    data = cast("dict[str, Any]", raw)
    if set(data) - {"version", "schemaVersion", "root", "metadata"}:
        raise ProjectError("unknown snapshot envelope fields")
    if "metadata" in data and not isinstance(data["metadata"], dict):
        raise ProjectError("metadata must be an object")
    snapshot = IRRoot(
        root=_node(data["root"]),
        schema_version=data["schemaVersion"],
        version=data["version"],
        metadata=data.get("metadata"),
    )
    validate_ir(snapshot, debug=True)
