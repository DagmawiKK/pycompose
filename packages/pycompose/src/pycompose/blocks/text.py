"""Text components: fields to type into, and text to read."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pycompose.blocks.components import Component, label
from pycompose.blocks.intents import SetText
from pycompose.errors import StateError
from pycompose.material3 import OutlinedTextField, Text
from pycompose.ui import Modifier

if TYPE_CHECKING:
    from pycompose.blocks.screen import View
    from pycompose.core.node import Node

__all__ = ["Markdown", "Number", "Textbox"]


class Textbox(Component):
    """A text field.

    Args:
        value: Its first text.
        label: What it is called on screen.
        lines: How many lines it shows; more than one wraps.
        placeholder: What it shows while empty.
        visible: Whether it is drawn.
        interactive: Whether the user can type into it.
    """

    def __init__(
        self,
        value: Any = None,
        *,
        label: str = "",
        lines: int = 1,
        placeholder: str = "",
        visible: bool = True,
        interactive: bool = True,
    ) -> None:
        super().__init__(value, label=label, visible=visible, interactive=interactive)
        self.lines = lines
        self.placeholder = placeholder

    def to_raw(self, value: Any) -> str:
        """Show any value as text.

        Args:
            value: The value.

        Returns:
            Its text.
        """
        return "" if value is None else str(value)

    def draw(self, view: View) -> Node:
        """Draw an outlined text field.

        Args:
            view: The state being drawn.

        Returns:
            A native OutlinedTextField.
        """
        return OutlinedTextField(
            id=self.id,
            value=view.value(self),
            label=label(self.label),
            placeholder=label(self.placeholder),
            single_line=self.lines == 1,
            min_lines=self.lines if self.lines > 1 else None,
            read_only=not self.interactive,
            on_value_change=SetText.bind(component=self.id),
            modifier=Modifier().fill_max_width(),
        )


class Number(Textbox):
    """A field holding a number; it reads as ``float``, or ``int`` with ``precision=0``.

    Args:
        value: Its first number.
        label: What it is called on screen.
        precision: Decimal places it rounds to, or None to keep every digit.
        visible: Whether it is drawn.
        interactive: Whether the user can type into it.
    """

    def __init__(
        self,
        value: float | None = None,
        *,
        label: str = "",
        precision: int | None = None,
        visible: bool = True,
        interactive: bool = True,
    ) -> None:
        self.precision = precision
        super().__init__(value, label=label, visible=visible, interactive=interactive)

    def to_python(self, raw: Any) -> float | int:
        """Read the typed text as a number.

        Args:
            raw: The field's text.

        Returns:
            The number.

        Raises:
            StateError: If the text is not a number, naming the field.
        """
        try:
            number = float(raw)
        except ValueError:
            raise StateError(
                f"{self.label or 'Number'}: {raw!r} is not a number"
            ) from None
        if self.precision is None:
            return number
        return round(number) if self.precision == 0 else round(number, self.precision)

    def to_raw(self, value: Any) -> str:
        """Show a number without a trailing ``.0``.

        Args:
            value: The number, text already typed, or None for zero.

        Returns:
            Its text.
        """
        if isinstance(value, str):
            return value
        number = float(value or 0)
        if self.precision is not None:
            number = round(number, self.precision)
        return str(int(number)) if number.is_integer() else str(number)


class Markdown(Component):
    """Text to read; plain text for now, formatting arrives later.

    Args:
        value: The text.
        visible: Whether it is drawn.
    """

    def __init__(self, value: Any = None, *, visible: bool = True) -> None:
        super().__init__(value, visible=visible, interactive=False)

    def to_raw(self, value: Any) -> str:
        """Show any value as text.

        Args:
            value: The value.

        Returns:
            Its text.
        """
        return "" if value is None else str(value)

    def draw(self, view: View) -> Node:
        """Draw the text.

        Args:
            view: The state being drawn.

        Returns:
            A native Text.
        """
        return Text(id=self.id, text=view.value(self))
