"""Material 3 action components."""

from pycompose.ui.base import Component


class Button(Component):
    """Button with text, registered on_click action id and optional enabled."""

    __slots__ = ()
    component_type = "Button"


class TextButton(Component):
    """Low-emphasis button with text, registered on_click action id and enabled."""

    __slots__ = ()
    component_type = "TextButton"
