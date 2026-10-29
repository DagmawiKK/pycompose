"""Layouts: how elements are arranged on a phone's screen."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pycompose import foundation, material3
from pycompose.blocks.intents import Expand, SetText
from pycompose.blocks.layout import Container
from pycompose.errors import StateError
from pycompose.foundation import AnimatedVisibility, FlowRow
from pycompose.material3 import Icon, ListItem, PrimaryTabRow, Text
from pycompose.ui import Modifier
from pycompose.values import materialIcon

if TYPE_CHECKING:
    from pycompose.blocks.screen import View
    from pycompose.core.node import Node

__all__ = ["Accordion", "Column", "Row", "Tab", "Tabs"]

GAP = 12
"""Space between stacked elements, in dp."""


class Column(Container):
    """Elements stacked top to bottom."""

    def draw(self, view: View) -> Node:
        """Stack the children.

        Args:
            view: The state being drawn.

        Returns:
            A native Column.
        """
        return foundation.Column(
            id=self.id,
            modifier=Modifier().fill_max_width(),
            children=[
                foundation.Column(
                    modifier=Modifier().padding(vertical=GAP / 2), children=[node]
                )
                for node in view.children(self)
            ],
        )


class Row(Container):
    """Elements side by side, wrapping onto a new line when they don't fit."""

    def draw(self, view: View) -> Node:
        """Lay the children out in a row that wraps.

        Args:
            view: The state being drawn.

        Returns:
            A native FlowRow.
        """
        return FlowRow(
            id=self.id,
            modifier=Modifier().fill_max_width(),
            children=view.children(self),
        )


class Tab(Column):
    """One page of :class:`Tabs`, named by its label.

    Args:
        label: The tab's name.
        visible: Whether it is drawn.
    """

    def __init__(self, label: str, *, visible: bool = True) -> None:
        super().__init__(visible=visible)
        self.label = label


class Tabs(Container):
    """Pages, one shown at a time; fill it with :class:`Tab` layouts."""

    @property
    def default(self) -> str:
        """The label of the page shown first.

        Returns:
            The first tab's label, or empty when there is none.
        """
        tabs = self._tabs()
        return tabs[0].label if tabs else ""

    def _tabs(self) -> list[Tab]:
        if any(not isinstance(child, Tab) for child in self.children):
            raise StateError("Tabs holds only Tab layouts")
        return [
            child for child in self.children if isinstance(child, Tab) and child.visible
        ]

    def draw(self, view: View) -> Node:
        """Draw the tab row and the selected page.

        Args:
            view: The state being drawn.

        Returns:
            A native Column.
        """
        tabs = self._tabs()
        chosen = view.state.values.get(self.id, self.default)
        index = next((i for i, tab in enumerate(tabs) if tab.label == chosen), 0)
        return foundation.Column(
            id=self.id,
            modifier=Modifier().fill_max_width(),
            children=[
                PrimaryTabRow(
                    selected_tab_index=index,
                    tabs=[
                        material3.Tab(
                            id=f"tab{i}",
                            selected=i == index,
                            on_click=SetText(component=self.id, value=tab.label),
                            text=Text(text=tab.label),
                        )
                        for i, tab in enumerate(tabs)
                    ],
                ),
                *([view.draw(tabs[index])] if tabs else []),
            ],
        )


class Accordion(Column):
    """A section that opens and closes under its label.

    Args:
        label: What the header shows.
        open: Whether it starts open.
        visible: Whether it is drawn.
    """

    def __init__(self, label: str, *, open: bool = False, visible: bool = True) -> None:
        super().__init__(visible=visible)
        self.label = label
        self.open = open

    def draw(self, view: View) -> Node:
        """Draw the header and, while open, the section.

        Args:
            view: The state being drawn.

        Returns:
            A native Column.
        """
        is_open = view.expanded(self, self.open)
        return foundation.Column(
            id=self.id,
            modifier=Modifier().fill_max_width(),
            children=[
                ListItem(
                    modifier=Modifier().clickable(
                        on_click=Expand(component=self.id, expanded=not is_open)
                    ),
                    headline_content=Text(text=self.label),
                    trailing_content=Icon(
                        image_vector=materialIcon(
                            name="Filled.KeyboardArrowUp"
                            if is_open
                            else "Filled.KeyboardArrowDown"
                        ),
                        content_description="Close" if is_open else "Open",
                    ),
                ),
                AnimatedVisibility(visible=is_open, children=[super().draw(view)]),
            ],
        )
