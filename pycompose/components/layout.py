"""Material 3 layout components."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pycompose.components.base import Component
from pycompose.components.modifiers import Modifier
from pycompose.core import Node
from pycompose.core.props import JsonValue
from pycompose.errors import IrValidationError
from pycompose.utils.json_canonical import FrozenJsonValue


class Column(Component):
    """Vertical children with optional horizontal_alignment and modifier."""

    __slots__ = ()
    component_type = "Column"


class Row(Component):
    """Horizontal children with optional vertical_alignment and modifier."""

    __slots__ = ()
    component_type = "Row"


class Box(Component):
    """Stacked children with optional content_alignment and modifier."""

    __slots__ = ()
    component_type = "Box"


class Scaffold(Component):
    """Screen content with optional container_color and modifier."""

    __slots__ = ()
    component_type = "Scaffold"

    def __init__(
        self,
        *,
        id: str | None = None,
        content: Node | Sequence[Node] | None = None,
        children: Sequence[Node] = (),
        modifier: Modifier | Mapping[str, JsonValue | FrozenJsonValue] | None = None,
        **props: JsonValue,
    ) -> None:
        """Construct content using either the content or children spelling.

        Args:
            id: Stable sibling key; None derives the node's path id.
            content: One content node or a sequence of content nodes.
            children: Content nodes when content is omitted.
            modifier: Ordered Modifier or a modifier wire object.
            **props: Registry-declared snake_case props.

        Raises:
            IrValidationError: If both content and children are supplied.
        """
        if content is not None:
            if children:
                raise IrValidationError(
                    "cannot supply both content and children", node_id=id or ""
                )
            children = (content,) if isinstance(content, Node) else content
        super().__init__(id=id, children=children, modifier=modifier, **props)
