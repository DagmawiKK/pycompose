"""Readable node paths for tests, from the table debug keeps off the wire.

Every snapshot names its nodes by short counters, in debug and release alike.
A test about identity asks what each counter stands for: the path debug keeps.
"""

from __future__ import annotations

from typing import Any

from pycompose.contract.catalog import SCHEMA_VERSION
from pycompose.core.ids import Handles
from pycompose.core.reuse import Reuse
from pycompose.ir import emit_ir, to_dict
from pycompose.state import State


def readable_reuse() -> Reuse:
    """Return a session's reuse that keeps readable paths, as debug does."""
    return Reuse(handles=Handles(readable=True))


def rename(document: dict[str, Any], reuse: Reuse) -> dict[str, Any]:
    """Return a snapshot dict with every node id replaced by its readable path."""
    table = reuse.handles.paths()

    def visit(node: dict[str, Any]) -> dict[str, Any]:
        renamed = {**node, "id": table[node["id"]]}
        if "children" in node:
            renamed["children"] = [visit(child) for child in node["children"]]
        return renamed

    return {**document, "root": visit(document["root"])}


def readable(state: State, version: str = SCHEMA_VERSION) -> dict[str, Any]:
    """Emit ``state`` and name each node by its readable path."""
    reuse = readable_reuse()
    return rename(to_dict(emit_ir(state, version, reuse)), reuse)


def ids(node: dict[str, Any]) -> list[str]:
    """Every id under ``node``, parents before children."""
    return [node["id"], *(i for child in node.get("children", []) for i in ids(child))]
