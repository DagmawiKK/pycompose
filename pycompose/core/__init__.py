"""pycompose.core — pure, stdlib-only, no components."""

from __future__ import annotations

from pycompose.core.ids import ROOT_ID, IdRegistry, child_id, id_path, make_path_id
from pycompose.core.node import Node, Props
from pycompose.core.props import (
    JsonValue,
    is_camel_case,
    props_from_kwargs,
    to_camel_case,
    to_snake_case,
)
from pycompose.core.registry_types import (
    AbstractComponentRegistry,
    ActionDef,
    ChildrenRule,
    ComponentDef,
    ComponentSpec,
    PropDef,
    Registry,
)

__all__ = [
    "ROOT_ID",
    "AbstractComponentRegistry",
    "ActionDef",
    "ChildrenRule",
    "ComponentDef",
    "ComponentSpec",
    "IdRegistry",
    "JsonValue",
    "Node",
    "PropDef",
    "Props",
    "Registry",
    "child_id",
    "id_path",
    "is_camel_case",
    "make_path_id",
    "props_from_kwargs",
    "to_camel_case",
    "to_snake_case",
]
