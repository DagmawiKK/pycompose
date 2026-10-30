"""Components: controls with a value, each drawn from native Material 3 ones.

A component's value is kept as the control reports it (``raw``), so a half-typed
number stays as typed; it is converted to a Python value only when an event
reads it, and back when an event writes it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from pycompose import material3
from pycompose.blocks.intents import Fire
from pycompose.blocks.layout import Element, Event
from pycompose.material3 import Text

if TYPE_CHECKING:
    from pycompose.blocks.screen import View
    from pycompose.model.nodes.node import Node

__all__ = ["Button", "Component", "label"]


def label(text: str) -> Node | None:
    """A label slot's text, or no slot for an empty one."""
    return Text(text=text) if text else None


class Component(Element):
    """A control with a value: what events read as inputs and write as outputs.

    Args:
        value: Its first value; None for the component's empty one.
        label: What it is called on screen.
        visible: Whether it is drawn.
        interactive: Whether the user can change it.
    """

    def __init__(
        self,
        value: Any = None,
        *,
        label: str = "",
        visible: bool = True,
        interactive: bool = True,
    ) -> None:
        super().__init__(visible=visible)
        self.label = label
        self.interactive = interactive
        # The MIME type a component picks a file of, or None for one that does not.
        self.accept: str | None = None
        self.default = self.to_raw(value)

    def to_python(self, raw: Any) -> Any:
        """Convert the value as the control holds it into what an event reads.

        Args:
            raw: The held value.

        Returns:
            The Python value.
        """
        return raw

    def to_raw(self, value: Any) -> Any:
        """Convert a value an event wrote into what the control holds.

        Args:
            value: The Python value.

        Returns:
            The held value.
        """
        return value

    def change(
        self,
        fn: Callable[..., Any],
        inputs: Component | Sequence[Component] | None = None,
        outputs: Component | Sequence[Component] | None = None,
    ) -> Event:
        """Run ``fn`` each time the user changes this component.

        Args:
            fn: Called with the inputs' values.
            inputs: The components it reads.
            outputs: The components it writes.

        Returns:
            The event.
        """
        return self.listen("change", fn, inputs, outputs)


class Button(Element):
    """A button that runs what listens to its click.

    Args:
        text: What it says.
        visible: Whether it is drawn.
        interactive: Whether it can be pressed.
    """

    def __init__(
        self, text: str = "Run", *, visible: bool = True, interactive: bool = True
    ) -> None:
        super().__init__(visible=visible)
        self.text = text
        self.interactive = interactive

    def click(
        self,
        fn: Callable[..., Any],
        inputs: Component | Sequence[Component] | None = None,
        outputs: Component | Sequence[Component] | None = None,
    ) -> Event:
        """Run ``fn`` each time the button is pressed.

        Args:
            fn: Called with the inputs' values.
            inputs: The components it reads.
            outputs: The components it writes.

        Returns:
            The event.
        """
        return self.listen("click", fn, inputs, outputs)

    def draw(self, view: View) -> Node:
        """Draw a filled button.

        Args:
            view: The state being drawn.

        Returns:
            A native Button.
        """
        del view
        return material3.Button(
            id=self.id,
            text=self.text,
            enabled=self.interactive,
            on_click=Fire(component=self.id),
        )
