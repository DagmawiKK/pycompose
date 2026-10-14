"""Material 3 action components."""

from pycompose.components.base import Component


class FilledButton(Component):
    """Button with text, registered on_click action id and optional enabled."""

    __slots__ = ()
    component_type = "FilledButton"


class TextButton(Component):
    """Low-emphasis button with text, registered on_click action id and enabled."""

    __slots__ = ()
    component_type = "TextButton"
