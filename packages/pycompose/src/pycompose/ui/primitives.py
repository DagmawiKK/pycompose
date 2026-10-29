"""Material 3 primitive components."""

from pycompose.ui.base import Component


class Text(Component):
    """Text with required text and optional style, color and modifier props."""

    __slots__ = ()
    component_type = "Text"


class Spacer(Component):
    """Empty space configured by its modifier."""

    __slots__ = ()
    component_type = "Spacer"
