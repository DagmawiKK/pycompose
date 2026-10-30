"""What a control on a blocks screen asks of its view model.

Every value event a native control reports carries one typed ``value``: text, a
number or a flag. One intent per value type serves every component, keyed by the
component's id, so no component defines intents of its own.
"""

from __future__ import annotations

from pycompose.ui.intents import Intent

__all__ = ["Expand", "Fire", "Pick", "SetFlag", "SetNumber", "SetText"]


class SetText(Intent):
    """Set a component's text, or the choice it shows.

    Attributes:
        component: The component's id.
        value: The text, supplied by the event or bound to a choice.
    """

    component: str
    value: str


class SetNumber(Intent):
    """Set a component's number.

    Attributes:
        component: The component's id.
        value: The number, supplied by the event.
    """

    component: str
    value: float


class SetFlag(Intent):
    """Set a component's flag.

    Attributes:
        component: The component's id.
        value: The flag, supplied by the event.
    """

    component: str
    value: bool


class Expand(Intent):
    """Open or close a menu or a section.

    Attributes:
        component: The element's id.
        expanded: Whether it is open, supplied by the event or bound.
    """

    component: str
    expanded: bool


class Pick(Intent):
    """Open the system picker for a component that holds a file.

    Attributes:
        component: The component's id.
    """

    component: str


class Fire(Intent):
    """Run what listens to a control's click.

    Attributes:
        component: The control's id.
    """

    component: str
