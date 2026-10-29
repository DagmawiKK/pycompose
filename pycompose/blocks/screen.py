"""Drawing a blocks screen: the declaration, read against the view model's state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pycompose.m3 import (
    AnimatedVisibility,
    Column,
    LinearProgressIndicatorWithoutProgress,
    Modifier,
)

if TYPE_CHECKING:
    from pycompose.blocks.components import Component
    from pycompose.blocks.layout import Container, Element
    from pycompose.blocks.view_model import BlocksState
    from pycompose.core.node import Node

__all__ = ["View"]


@dataclass(frozen=True)
class View:
    """One state of a blocks screen, as its elements draw it.

    Attributes:
        state: The view model's state.
        outputs: The ids of components some event writes to; only these can
            be busy, so only these carry a progress indicator.
    """

    state: BlocksState
    outputs: frozenset[str]

    def value(self, component: Component) -> Any:
        """Return the value a component shows: the last one set, else its first.

        Args:
            component: The component.

        Returns:
            Its value as the screen holds it.
        """
        return self.state.values.get(component.id, component.default)

    def expanded(self, element: Element, default: bool = False) -> bool:
        """Return whether a menu or section is open.

        Args:
            element: The element.
            default: Whether it starts open.

        Returns:
            Its current openness.
        """
        return self.state.expanded.get(element.id, default)

    def children(self, container: Container) -> list[Node]:
        """Draw a layout's visible children, in order.

        Args:
            container: The layout.

        Returns:
            Their nodes.
        """
        return [self.draw(child) for child in container.children if child.visible]

    def draw(self, element: Element) -> Node:
        """Draw one element; an output also shows when it is being computed.

        The indicator is always declared and only shown while busy, so a field
        keeps its focus and caret when its event starts and ends.

        Args:
            element: The element.

        Returns:
            Its nodes.
        """
        node = element.draw(self)
        if element.id not in self.outputs:
            return node
        return Column(
            id=element.id,
            modifier=Modifier().fill_max_width(),
            children=[
                node,
                AnimatedVisibility(
                    visible=element.id in self.state.busy,
                    children=[
                        LinearProgressIndicatorWithoutProgress(
                            modifier=Modifier().fill_max_width()
                        )
                    ],
                ),
            ],
        )
