"""Selection components: a flag, a number on a range, or one of a list of choices."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from pycompose import ui
from pycompose.app.blocks.components import Component, label
from pycompose.app.blocks.intents import Expand, SetFlag, SetNumber, SetText
from pycompose.errors import StateError
from pycompose.ui import (
    DropdownMenuItem,
    ExposedDropdownMenu,
    ExposedDropdownMenuAnchorType,
    ExposedDropdownMenuBox,
    Modifier,
    OutlinedTextField,
    RadioButton,
    Range,
    Row,
    Text,
)

if TYPE_CHECKING:
    from pycompose.app.blocks.screen import View
    from pycompose.model.nodes.node import Node

__all__ = ["Checkbox", "Dropdown", "Radio", "Slider"]


class Slider(Component):
    """A number chosen by dragging between two ends.

    Args:
        minimum: The left end.
        maximum: The right end.
        value: Its first number; the left end when None.
        step: The distance between allowed values, or None for any.
        label: What it is called on screen.
        visible: Whether it is drawn.
        interactive: Whether the user can drag it.

    Raises:
        StateError: If the ends are out of order or the step is not positive.
    """

    def __init__(
        self,
        minimum: float = 0,
        maximum: float = 100,
        value: float | None = None,
        *,
        step: float | None = None,
        label: str = "",
        visible: bool = True,
        interactive: bool = True,
    ) -> None:
        if maximum <= minimum or (step is not None and step <= 0):
            raise StateError("a slider needs minimum < maximum and a positive step")
        self.minimum, self.maximum, self.step = minimum, maximum, step
        super().__init__(
            minimum if value is None else value,
            label=label,
            visible=visible,
            interactive=interactive,
        )

    def to_raw(self, value: Any) -> float:
        """Keep a number inside the ends.

        Args:
            value: The number.

        Returns:
            It, clamped to the ends.
        """
        return min(max(float(value), self.minimum), self.maximum)

    def draw(self, view: View) -> Node:
        """Draw the label with the value, and the slider under it.

        Args:
            view: The state being drawn.

        Returns:
            A native Column.
        """
        value = view.value(self)
        shown = f"{value:g}"
        steps = (
            max(round((self.maximum - self.minimum) / self.step) - 1, 0)
            if self.step
            else None
        )
        return ui.Column(
            id=self.id,
            modifier=Modifier().fill_max_width(),
            children=[
                Text(text=f"{self.label}: {shown}" if self.label else shown),
                ui.Slider(
                    value=value,
                    value_range=Range(self.minimum, self.maximum),
                    steps=steps,
                    enabled=self.interactive,
                    on_value_change_finished=SetNumber.bind(component=self.id),
                ),
            ],
        )


class Checkbox(Component):
    """A flag, ticked or not.

    Args:
        value: Whether it starts ticked.
        label: What it is called on screen.
        visible: Whether it is drawn.
        interactive: Whether the user can tick it.
    """

    def to_raw(self, value: Any) -> bool:
        """Read any value as a flag.

        Args:
            value: The value.

        Returns:
            Its truth.
        """
        return bool(value)

    def draw(self, view: View) -> Node:
        """Draw the box beside its label.

        Args:
            view: The state being drawn.

        Returns:
            A native Row.
        """
        return Row(
            id=self.id,
            vertical_alignment="centerVertically",
            children=[
                ui.Checkbox(
                    checked=view.value(self),
                    enabled=self.interactive,
                    on_checked_change=SetFlag.bind(component=self.id),
                ),
                Text(text=self.label),
            ],
        )


class _Choice(Component):
    """A component holding one of a fixed list of choices."""

    def __init__(
        self,
        choices: Sequence[str],
        value: str | None = None,
        *,
        label: str = "",
        visible: bool = True,
        interactive: bool = True,
    ) -> None:
        self.choices = tuple(str(choice) for choice in choices)
        if not self.choices or (value is not None and str(value) not in self.choices):
            raise StateError(
                "a choice needs choices, and its value must be one of them"
            )
        super().__init__(value, label=label, visible=visible, interactive=interactive)

    def to_raw(self, value: Any) -> str:
        """Hold a choice by its text.

        Args:
            value: The choice; empty for none.

        Returns:
            Its text.
        """
        return "" if value is None else str(value)


class Radio(_Choice):
    """One of a few choices, all shown, one selected.

    Args:
        choices: The choices, in order.
        value: The one selected first, or None for none.
        label: What it is called on screen.
        visible: Whether it is drawn.
        interactive: Whether the user can choose.
    """

    def draw(self, view: View) -> Node:
        """Draw the label and one radio button per choice.

        Args:
            view: The state being drawn.

        Returns:
            A native Column.
        """
        chosen = view.value(self)
        return ui.Column(
            id=self.id,
            children=[
                *([Text(text=self.label)] if self.label else []),
                *(
                    self._option(i, choice, choice == chosen)
                    for i, choice in enumerate(self.choices)
                ),
            ],
        )

    def _option(self, index: int, choice: str, selected: bool) -> Node:
        """Draw one choice: the whole row picks it, as Material's radio groups do."""
        pick = SetText(component=self.id, value=choice)
        return Row(
            id=f"choice{index}",
            vertical_alignment="centerVertically",
            modifier=Modifier()
            .fill_max_width()
            .clickable(on_click=pick, enabled=self.interactive),
            children=[
                RadioButton(selected=selected, enabled=self.interactive, on_click=pick),
                Text(text=choice),
            ],
        )


class Dropdown(_Choice):
    """One of many choices, picked from a menu.

    Args:
        choices: The choices, in order.
        value: The one selected first, or None for none.
        label: What it is called on screen.
        visible: Whether it is drawn.
        interactive: Whether the user can choose.
    """

    def draw(self, view: View) -> Node:
        """Draw a read-only field that opens the menu of choices.

        Args:
            view: The state being drawn.

        Returns:
            A native ExposedDropdownMenuBox.
        """
        expanded = self.interactive and view.expanded(self)
        return ExposedDropdownMenuBox(
            id=self.id,
            expanded=expanded,
            on_expanded_change=Expand.bind(component=self.id),
            children=[
                OutlinedTextField(
                    value=view.value(self),
                    label=label(self.label),
                    read_only=True,
                    single_line=True,
                    on_value_change=SetText.bind(component=self.id),
                    modifier=Modifier()
                    .menu_anchor(
                        ExposedDropdownMenuAnchorType("PrimaryNotEditable"),
                        enabled=self.interactive,
                    )
                    .fill_max_width(),
                ),
                ExposedDropdownMenu(
                    expanded=expanded,
                    on_dismiss_request=Expand(component=self.id, expanded=False),
                    children=[
                        DropdownMenuItem(
                            id=f"choice{i}",
                            text=Text(text=choice),
                            on_click=SetText(component=self.id, value=choice),
                        )
                        for i, choice in enumerate(self.choices)
                    ],
                ),
            ],
        )
