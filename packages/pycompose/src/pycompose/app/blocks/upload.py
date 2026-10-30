"""Upload components: a file the user picks with the system picker.

The host copies the pick into the app's media cache and hands back its path,
which is what an event reads: open it like any file.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pycompose import ui
from pycompose.app.blocks.components import Component
from pycompose.app.blocks.intents import Pick
from pycompose.app.blocks.layout import Event
from pycompose.ui import Modifier, OutlinedButton, Text

if TYPE_CHECKING:
    from pycompose.app.blocks.screen import View
    from pycompose.model.nodes.node import Node

__all__ = ["File", "UploadButton"]


class File(Component):
    """A file the user picks, shown by name.

    Args:
        label: What it is called on screen.
        accept: The MIME type to pick, such as ``application/pdf``.
        visible: Whether it is drawn.
    """

    def __init__(
        self, *, label: str = "", accept: str = "*/*", visible: bool = True
    ) -> None:
        super().__init__(None, label=label, visible=visible)
        self.accept = accept

    def to_python(self, raw: Any) -> str | None:
        """Hand an event the picked file's path.

        Args:
            raw: The held path, or empty.

        Returns:
            The path, or None before a pick.
        """
        return raw or None

    def to_raw(self, value: Any) -> str:
        """Hold a file by its path.

        Args:
            value: The path, or None for none.

        Returns:
            The path as text, or empty.
        """
        return "" if value is None else str(value)

    def draw(self, view: View) -> Node:
        """Draw the label, the picked file's name and the button that picks one.

        Args:
            view: The state being drawn.

        Returns:
            A native Column.
        """
        path = view.value(self)
        return ui.Column(
            id=self.id,
            modifier=Modifier().fill_max_width(),
            children=[
                *([Text(text=self.label)] if self.label else []),
                Text(
                    text=Path(path).name if path else "No file chosen",
                    style="bodySmall",
                ),
                OutlinedButton(
                    on_click=Pick(component=self.id),
                    enabled=self.interactive,
                    children=[Text(text="Change file" if path else "Choose file")],
                ),
            ],
        )


class UploadButton(File):
    """A button that picks a file and runs what listens to the upload.

    Its value is the picked file's path, so a listener reads it by naming the
    button among its inputs.

    Args:
        text: What it says.
        accept: The MIME type to pick; ``image/*`` opens the photo picker.
        visible: Whether it is drawn.
    """

    def __init__(
        self, text: str = "Upload a file", *, accept: str = "*/*", visible: bool = True
    ) -> None:
        super().__init__(accept=accept, visible=visible)
        self.text = text

    def upload(
        self,
        fn: Callable[..., Any],
        inputs: Component | Sequence[Component] | None = None,
        outputs: Component | Sequence[Component] | None = None,
    ) -> Event:
        """Run ``fn`` each time the user picks a file.

        Args:
            fn: Called with the inputs' values.
            inputs: The components it reads; the button itself for the file.
            outputs: The components it writes.

        Returns:
            The event.
        """
        return self.listen("change", fn, inputs, outputs)

    def draw(self, view: View) -> Node:
        """Draw a filled button that opens the picker.

        Args:
            view: The state being drawn.

        Returns:
            A native Button.
        """
        del view
        return ui.Button(id=self.id, text=self.text, on_click=Pick(component=self.id))
