"""Lazy list construction with explicit stable item ids."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pycompose.components.base import Component
from pycompose.components.modifiers import Modifier
from pycompose.core import Node
from pycompose.core.props import JsonValue
from pycompose.errors import IrValidationError
from pycompose.utils.json_canonical import FrozenJsonValue


class LazyColumn(Component):
    """Vertical lazy items with stable sibling keys, never positional ids."""

    __slots__ = ()
    component_type = "LazyColumn"

    def __init__(
        self,
        *,
        id: str | None = None,
        items: Sequence[Node] = (),
        children: Sequence[Node] = (),
        modifier: Modifier | Mapping[str, JsonValue | FrozenJsonValue] | None = None,
        **props: JsonValue,
    ) -> None:
        """Construct items using either the items or children spelling.

        Args:
            id: Stable sibling key; None derives the node's path id.
            items: Item nodes, each with an explicit stable id.
            children: Item nodes when items is omitted.
            modifier: Ordered Modifier or a modifier wire object.
            **props: Registry-declared snake_case props.

        Raises:
            IrValidationError: If both items and children are supplied.
        """
        if items and children:
            raise IrValidationError(
                "cannot supply both items and children", node_id=id or ""
            )
        super().__init__(id=id, children=items or children, modifier=modifier, **props)
